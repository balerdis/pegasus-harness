#!/usr/bin/env bash
# Instala Pegasus en una cuenta Linux limpia: nvm + Node LTS, OpenCode y el
# binario de pegasus, en ese orden, y deja el resultado listo para trabajar.
#
# Pensado para correrse así, como asset de un release (bash lee la tubería de
# a poco, por eso todo el script vive adentro de funciones — ver el comentario
# junto a la última línea):
#
#   curl -fsSL https://github.com/balerdis/pegasus-harness/releases/latest/download/install.sh | bash
#
#   ./install.sh                     detecta, muestra el preflight, pide confirmación e instala
#   ./install.sh --verify            informa el estado, no cambia nada
#   ./install.sh --yes               salta la confirmación
#   ./install.sh --no-run            instala lo que falte, pero no lanza nada al final; dice qué habría lanzado
#   ./install.sh --bin-dir DIR       instala el binario de pegasus en DIR en vez de ~/.local/bin
#   ./install.sh --opencode-version X   fija la versión de OpenCode a instalar
#   ./install.sh --opencode-ultima      instala la última versión de OpenCode publicada
#
set -euo pipefail

# --- Valores por defecto, ajustables por flag ---

BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
MODO='instalar'
NO_RUN=0
CONFIRMAR=1

# Donde el instalador oficial de OpenCode deja el binario -- ver el
# comentario dentro de instalar_opencode. Se fija acá, una sola vez, porque
# tanto instalar_opencode como la guía de PATH del final necesitan el mismo
# valor.
OPENCODE_BIN_DIR="$HOME/.opencode/bin"

# El PATH tal como llegó, antes de que cualquier "export PATH=..." de este
# script lo toque. La guía de PATH del final (ver mostrar_guia_path) tiene
# que juzgar contra ESTE valor, no contra el PATH ya modificado del propio
# proceso -- si mirara el PATH en vivo después de asegurar_path, un
# directorio que este mismo script acaba de agregar (sólo para que el exec
# de más abajo lo encuentre) se vería como "ya estaba", y la persona nunca
# se enteraría de que en SU terminal real -- la que sigue viva del otro lado
# del pipe -- ese directorio sigue faltando.
ORIGINAL_PATH="$PATH"

# Version de OpenCode a instalar. Se fija por el mismo motivo que
# creacion-usuario.sh fija la suya: sin autenticar, la API de GitHub que
# resuelve "la última versión" permite 60 pedidos por hora por IP, y una
# tarde de pruebas la agota — el instalador falla entonces con "Failed to
# fetch version information". Con una versión pedida, ni la consulta.
VERSION_OPENCODE='1.18.25'

# Version del instalador de nvm (no de Node: eso lo elige "--lts" más abajo).
# Se fija por la misma razón que arriba: sin versión, el script de nvm
# consulta GitHub para resolver la última, y ese pedido también cuenta contra
# el límite de 60/hora sin autenticar.
NVM_VERSION='v0.40.7'

# Los tres assets que publica cada release, en la ruta que no gasta cupo de
# API: es un redirect HTTP servido por GitHub, no una llamada a
# api.github.com, así que no cuenta contra ningún límite de tasa. Es la razón
# entera por la que no se resuelve un tag acá adentro.
#
# PEGASUS_INSTALL_BASE_URL es una costura para poder probar la descarga real
# (con verificación de checksum incluida) contra un directorio local, sin
# tocar la red — no es una opción pensada para que la use una persona, así
# que no se documenta en INSTALL.md. Sin esa variable, cae en la URL de
# siempre.
BASE_URL="${PEGASUS_INSTALL_BASE_URL:-https://github.com/balerdis/pegasus-harness/releases/latest/download}"

# Directorio temporal de la descarga de pegasus. Global a propósito, no
# `local` a la función que lo crea: el `trap ... EXIT` que lo limpia se
# ejecuta después de que esa función ya retornó, y bajo "set -u" una variable
# `local` fuera de su función es una variable inexistente, no vacía — el
# trap fallaría con "unbound variable" en vez de limpiar.
PEGASUS_TMPDIR=''

fallar() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
titulo() { printf '\n=== %s ===\n' "$*"; }
ok()     { printf '  ✔ %s\n' "$*"; }
info()   { printf '  %s\n' "$*"; }

uso() {
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
}

# --- Argumentos ---

parsear_argumentos() {
  while (($#)); do
    case "$1" in
      --verify) MODO='verificar'; shift ;;
      --yes|-y) CONFIRMAR=0; shift ;;
      --no-run) NO_RUN=1; shift ;;
      --bin-dir)
        (($# >= 2)) || fallar '--bin-dir necesita un directorio'
        BIN_DIR=$2; shift 2 ;;
      --opencode-version)
        (($# >= 2)) || fallar '--opencode-version necesita un numero'
        VERSION_OPENCODE=$2; shift 2 ;;
      --opencode-ultima) VERSION_OPENCODE=''; shift ;;
      --help|-h) uso; exit 0 ;;
      *) fallar "argumento no soportado: $1" ;;
    esac
  done
}

# --- Guarda de root ---
#
# EUID 0 dejaría archivos de este usuario con dueño root en su propio home, y
# eso rompe la cuenta en silencio (permisos, $HOME de root, etc). El uso
# previsto para correr esto en una cuenta ajena es "sudo -u <usuario> -i" y
# recién ahí "./install.sh" ya como esa cuenta — nunca "sudo ./install.sh".
rechazar_root() {
  ((EUID != 0)) \
    || fallar 'no corras esto como root. Para probar en otra cuenta usá: sudo -u <usuario> -i, y desde esa sesión corré ./install.sh sin sudo.'
}

# --- Detección: no instala nada, sólo llena variables ---

PY_PRESENTE=0
PY_OK=0
PY_VERSION=''

detectar_python() {
  if command -v python3 >/dev/null 2>&1; then
    PY_PRESENTE=1
    PY_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || printf 'desconocida')
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      PY_OK=1
    else
      PY_OK=0
    fi
  else
    PY_PRESENTE=0
    PY_OK=0
    PY_VERSION=''
  fi
}

CURL_PRESENTE=0

detectar_curl() {
  command -v curl >/dev/null 2>&1 && CURL_PRESENTE=1 || CURL_PRESENTE=0
}

NODE_PRESENTE=0
NODE_VERSION=''

detectar_node() {
  if command -v node >/dev/null 2>&1; then
    NODE_PRESENTE=1
    NODE_VERSION=$(node --version 2>&1 | head -1)
  else
    NODE_PRESENTE=0
    NODE_VERSION=''
  fi
}

OPENCODE_PRESENTE=0
OPENCODE_VERSION=''

detectar_opencode() {
  if command -v opencode >/dev/null 2>&1; then
    OPENCODE_PRESENTE=1
    OPENCODE_VERSION=$(opencode --version 2>&1 | head -1)
  else
    OPENCODE_PRESENTE=0
    OPENCODE_VERSION=''
  fi
}

PEGASUS_PRESENTE=0
PEGASUS_VERSION=''
PEGASUS_RUTA=''

detectar_pegasus() {
  if command -v pegasus >/dev/null 2>&1; then
    PEGASUS_PRESENTE=1
    PEGASUS_RUTA=$(command -v pegasus)
    PEGASUS_VERSION=$(pegasus --version 2>&1 | head -1)
  elif [[ -x "$BIN_DIR/pegasus" ]]; then
    PEGASUS_PRESENTE=1
    PEGASUS_RUTA="$BIN_DIR/pegasus"
    PEGASUS_VERSION=$("$BIN_DIR/pegasus" --version 2>&1 | head -1)
  else
    PEGASUS_PRESENTE=0
    PEGASUS_VERSION=''
    PEGASUS_RUTA=''
  fi
}

# $1: la cadena de PATH a inspeccionar. $2: el directorio buscado. Tomar la
# cadena de PATH como parámetro (en vez de leer siempre "$PATH" en vivo) es
# lo que le permite tanto a detectar_path (PATH en vivo, para el preflight)
# como a mostrar_guia_path (ORIGINAL_PATH, para el cierre) compartir una
# sola implementación sin pisarse.
dir_en_path() {
  case ":$1:" in
    *":$2:"*) return 0 ;;
    *) return 1 ;;
  esac
}

BIN_DIR_EN_PATH=0

detectar_path() {
  dir_en_path "$PATH" "$BIN_DIR" && BIN_DIR_EN_PATH=1 || BIN_DIR_EN_PATH=0
}

detectar_todo() {
  detectar_python
  detectar_curl
  detectar_node
  detectar_opencode
  detectar_pegasus
  detectar_path
}

# Qué falta instalar. Se calcula una sola vez a partir de la detección, y de
# acá sale el bloque "Se instalará" del preflight. Qué se lanza al final ya
# NO sale de acá: sale de lo que la instalación hizo de verdad (ver
# ALGO_SE_INSTALO más abajo), porque bajo --no-run sí se instala de verdad.
FALTA_NODE=0
FALTA_OPENCODE=0
FALTA_PEGASUS=0
FALTA_ALGO=0

calcular_faltantes() {
  ((NODE_PRESENTE)) && FALTA_NODE=0 || FALTA_NODE=1
  ((OPENCODE_PRESENTE)) && FALTA_OPENCODE=0 || FALTA_OPENCODE=1
  ((PEGASUS_PRESENTE)) && FALTA_PEGASUS=0 || FALTA_PEGASUS=1
  if ((FALTA_NODE || FALTA_OPENCODE || FALTA_PEGASUS)); then
    FALTA_ALGO=1
  else
    FALTA_ALGO=0
  fi
}

# Lo que este script NO puede instalar sin arriesgarse a romper la cuenta: un
# python3 ausente o viejo (elegir el gestor de paquetes de la distro es
# decisión de la persona, no algo que este script deba adivinar), o un curl
# ausente (sin él no hay forma de descargar nada de lo que sigue). Las tres
# faltas bloquean por igual, en --verify y en una corrida real por igual: un
# python3 ausente no es un ambiente más "viable" que uno presente pero viejo,
# así que ninguno de los dos puede reportar éxito.
BLOQUEADO=0

calcular_bloqueo() {
  BLOQUEADO=0
  ((PY_PRESENTE)) || BLOQUEADO=1
  ((PY_PRESENTE)) && ! ((PY_OK)) && BLOQUEADO=1
  ((CURL_PRESENTE)) || BLOQUEADO=1
}

# --- Preflight ---
mostrar_preflight() {
  titulo 'Chequeo de requisitos'

  if ((PY_PRESENTE)); then
    if ((PY_OK)); then
      ok "python3 $PY_VERSION"
    else
      info "python3 $PY_VERSION encontrado, pero Pegasus necesita 3.12 o superior"
    fi
  else
    info 'python3: no encontrado'
  fi

  if ((CURL_PRESENTE)); then
    ok 'curl disponible'
  else
    info 'curl: no encontrado'
  fi

  # Bajo --verify, si ya sabemos que ningún run real podría avanzar, no tiene
  # sentido mostrar un plan de instalación ni, más abajo, una línea de "se
  # lanzaría tal cosa": ninguna de las dos cosas va a pasar nunca así como
  # están las cosas ahora. Se lo decimos así de directo y cortamos acá.
  if [[ "$MODO" == 'verificar' ]] && ((BLOQUEADO)); then
    titulo 'No se puede continuar'
    info 'No se puede seguir hasta resolver lo de arriba: sin eso, ninguna instalación real podría avanzar.'
    return 0
  fi

  titulo 'Se instalará'
  local algo_para_instalar=0
  if ((FALTA_NODE)); then
    info "Node LTS, vía nvm $NVM_VERSION"
    algo_para_instalar=1
  fi
  if ((FALTA_OPENCODE)); then
    if [[ -n "$VERSION_OPENCODE" ]]; then
      info "OpenCode $VERSION_OPENCODE"
    else
      info 'OpenCode, última versión publicada'
    fi
    algo_para_instalar=1
  fi
  if ((FALTA_PEGASUS)); then
    info "el binario pegasus, en $BIN_DIR"
    algo_para_instalar=1
  fi
  ((algo_para_instalar)) || info 'nada: ya está todo instalado'

  titulo 'Ya presente'
  local algo_presente=0
  ((NODE_PRESENTE)) && { ok "node $NODE_VERSION"; algo_presente=1; }
  ((OPENCODE_PRESENTE)) && { ok "opencode $OPENCODE_VERSION"; algo_presente=1; }
  ((PEGASUS_PRESENTE)) && { ok "pegasus $PEGASUS_VERSION ($PEGASUS_RUTA)"; algo_presente=1; }
  ((algo_presente)) || info 'nada todavía'

  titulo 'PATH'
  if ((BIN_DIR_EN_PATH)); then
    ok "$BIN_DIR ya está en el PATH"
  else
    info "$BIN_DIR todavía no está en el PATH"
  fi
}

# Sólo se llama en una corrida real (nunca bajo --verify: ese caso ya cortó
# arriba, en mostrar_preflight, con exit vía main). Los "hints" de abajo son
# eso: pistas para que la persona los corra ella misma. Este script nunca
# instala un python3 de sistema — es específico de cada distro y, si se elige
# mal, se rompe algo que este instalador no puede arreglar.
fallar_por_requisitos_bloqueantes() {
  if ((PY_PRESENTE)) && ! ((PY_OK)); then
    fallar "Pegasus necesita Python 3.12 o superior (lo exige pyproject.toml); se encontró python3 $PY_VERSION.
Este script no instala ni actualiza Python: es específico de cada distribución y una elección
equivocada puede romper el sistema. Pistas (no ejecutadas por este script):
  Debian/Ubuntu: sudo apt install python3
  Fedora/RHEL:   sudo dnf install python3"
  fi

  if ! ((PY_PRESENTE)); then
    fallar "Pegasus necesita Python 3.12 o superior (lo exige pyproject.toml); no se encontró python3.
Este script no instala Python. Pistas (no ejecutadas por este script):
  Debian/Ubuntu: sudo apt install python3
  Fedora/RHEL:   sudo dnf install python3"
  fi

  ((CURL_PRESENTE)) || fallar 'falta curl: sin él este script no puede descargar nada. Instalalo con el gestor de paquetes de tu distribución (por ejemplo: sudo apt install curl) y volvé a correr este script.'
}

# --- Terminal controladora ---
#
# La usan tanto `confirmar` (para saber si hay a quién preguntarle) como
# `lanzar` (para saber si el programa final -- pegasus u opencode, los dos
# TUIs -- va a tener una terminal real, o si más vale no exec'earlo). Una
# sola función para que las dos nunca puedan quedar en desacuerdo: la
# razón para extraerla es exactamente la misma que ya se documentó abajo,
# en el comentario grande de `confirmar`, un escalón más adentro -- el bug
# original ("exec \"$LANZAR\"" hereda un stdin muerto) es el mismo bug que
# ya se había resuelto acá, sólo que sin generalizar.
#
# El chequeo tiene que ABRIR /dev/tty de verdad, no sólo mirar sus bits de
# permiso: `[[ -r /dev/tty ]]` da "legible" igual aunque no haya ninguna
# terminal controladora (el nodo del dispositivo existe y es legible por
# cualquiera; lo que falla es abrirlo). Se prueba en un subshell para poder
# silenciar el "No such device or address" que bash imprime solo si el
# intento de abrir falla adentro del proceso principal.
hay_terminal_controladora() {
  (exec 0</dev/tty) 2>/dev/null
}

confirmar() {
  ((CONFIRMAR)) || return 0
  printf '\n'

  # NO leer de stdin acá, bajo ninguna circunstancia -- ver por qué:
  #
  # El uso publicado de este script es "curl ... | bash". Cuando bash recibe
  # el script por una tubería, fd 0 ES esa tubería: bash tiene que consumir
  # el archivo entero (para encontrar el cierre de cada función, entre otras
  # cosas) antes de que "main" corra una sola línea. Para cuando esta
  # función se ejecuta, stdin ya está en EOF. Un "read" leyendo de stdin ahí
  # devuelve fallo en silencio, y bajo "set -e" eso aborta la función ANTES
  # de que su propio "case"/"fallar" lleguen a correr: la persona ve el
  # preflight, una línea en blanco, y el script termina con código 1 sin
  # ningún mensaje -- ni siquiera el "cancelado" de acá abajo. Es el mismo
  # tipo de trampa que ya se documentó para el agente en
  # INSTALL_BY_AGENT.md ("nadie va a escribir 'y' en un pipe"), sólo que acá
  # aplica igual de fuerte al camino humano, que es justo el que
  # INSTALL.md pone primero.
  #
  # La terminal real de quien está tipeando, en cambio, sigue disponible en
  # /dev/tty aunque stdin sea una tubería -- así se pregunta. Si no hay
  # ninguna terminal controladora (por ejemplo, corriendo en CI sin tty, o
  # con stdin explícitamente cerrado), no hay a quién preguntarle: no se
  # sigue a ciegas ni se muere en silencio como antes, se corta con un
  # mensaje que nombra --yes como la salida para ese caso.
  #
  # (Si a alguien se le ocurre "simplificar" esto de vuelta a
  # `read -r -p ... respuesta` a secas: no. Es exactamente el bug de arriba.)
  if ! hay_terminal_controladora; then
    fallar 'no hay una terminal para pedir confirmación (por ejemplo, corriendo sin tty o con stdin cerrado). Usá --yes para saltear la confirmación.'
  fi

  local respuesta
  read -r -p '¿Instalar lo que falta? [y/N] ' respuesta < /dev/tty
  case "$respuesta" in
    y|Y|yes|YES|si|Si|SI) return 0 ;;
    *) fallar 'cancelado, no se cambió nada' ;;
  esac
}

# --- Instalación, en orden de dependencia ---

# Si esta corrida instaló algo de verdad. Es lo que decide qué se lanza al
# final (ver decidir_lanzamiento) — no FALTA_ALGO, que sólo dice qué faltaba
# al empezar y bajo --no-run seguiría siendo cierto aunque la instalación ya
# haya pasado.
ALGO_SE_INSTALO=0

instalar_node() {
  titulo 'Node (vía nvm)'
  if ((NODE_PRESENTE)); then
    info "ya instalado: $NODE_VERSION"
    return 0
  fi
  ALGO_SE_INSTALO=1

  # Mismo esquema que usa el propio snippet de nvm: si XDG_CONFIG_HOME está
  # definida, NVM_DIR va debajo; si no, cae en el default histórico ~/.nvm.
  local nvm_dir
  nvm_dir="$([ -z "${XDG_CONFIG_HOME-}" ] && printf '%s' "$HOME/.nvm" || printf '%s' "$XDG_CONFIG_HOME/nvm")"
  export NVM_DIR="$nvm_dir"

  # El instalador de nvm crea NVM_DIR con un mkdir pelado, no con mkdir -p, así
  # que si el directorio padre todavía no existe se muere con "Failed to create
  # directory". Un usuario Linux recién creado con useradd desde /etc/skel no
  # tiene ~/.config hasta que algo lo crea, y este script es justamente para
  # esos ambientes. Se crea el padre, no NVM_DIR: que lo cree nvm, que es quien
  # decide qué hacer según exista o no.
  mkdir -p "$(dirname "$NVM_DIR")" || fallar "no se pudo crear $(dirname "$NVM_DIR")"

  if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
    info "instalando nvm $NVM_VERSION..."
    curl -o- "https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_VERSION/install.sh" | bash \
      || fallar 'no se pudo instalar nvm'
  else
    info 'nvm ya estaba instalado'
  fi

  # El instalador de nvm sólo agrega el snippet a ~/.bashrc; esta shell ya
  # arrancó y no lo leyó, así que sin este source "nvm install" falla con
  # "Command 'nvm' not found" — es exactamente lo que le pasó al usuario.
  # shellcheck disable=SC1091
  source "$NVM_DIR/nvm.sh"

  info 'instalando Node LTS...'
  nvm install --lts || fallar 'no se pudo instalar Node LTS'
  ok "Node $(node --version) instalado"
}

instalar_opencode() {
  titulo 'OpenCode'
  if ((OPENCODE_PRESENTE)); then
    info "ya instalado: $OPENCODE_VERSION"
    return 0
  fi
  ALGO_SE_INSTALO=1

  if [[ -n "$VERSION_OPENCODE" ]]; then
    info "instalando OpenCode $VERSION_OPENCODE con el mecanismo oficial..."
    curl -fsSL https://opencode.ai/install | VERSION="$VERSION_OPENCODE" bash \
      || fallar "falló la instalación de OpenCode $VERSION_OPENCODE"
  else
    info 'instalando la última versión de OpenCode con el mecanismo oficial...'
    info 'esto consulta la API de GitHub, que sin autenticar permite 60 pedidos por hora por IP'
    curl -fsSL https://opencode.ai/install | bash \
      || fallar 'falló la instalación de OpenCode; si dice "Failed to fetch version information", es el límite de la API de GitHub: esperá o usá --opencode-version'
  fi

  # El instalador oficial deja el binario en $OPENCODE_BIN_DIR y sólo lo
  # agrega a ~/.bashrc; esta shell ya arrancó, así que hace falta lo mismo
  # acá.
  export PATH="$OPENCODE_BIN_DIR:$PATH"
  command -v opencode >/dev/null 2>&1 \
    || fallar 'OpenCode se instaló pero no quedó en el PATH; revisá ~/.bashrc'
  ok "instalado: $(opencode --version 2>&1 | head -1)"
}

instalar_pegasus() {
  titulo 'Binario de pegasus'
  if ((PEGASUS_PRESENTE)); then
    info "ya instalado: $PEGASUS_VERSION ($PEGASUS_RUTA)"
    info "para reemplazarlo por el más nuevo publicado usá: pegasus upgrade"
    return 0
  fi
  ALGO_SE_INSTALO=1

  mkdir -p "$BIN_DIR" || fallar "no se pudo crear $BIN_DIR"

  PEGASUS_TMPDIR=$(mktemp -d) || fallar 'no se pudo crear un directorio temporal'
  # Red de seguridad para los caminos de error de abajo (falla la descarga,
  # falla el checksum): "fallar" hace "exit", y ahí sí corren los traps
  # pendientes. En el camino feliz este trap NO alcanza a limpiar nada solo
  # -- "lanzar" termina con "exec", que reemplaza esta imagen de proceso sin
  # correr traps pendientes -- por eso además se limpia a mano, explícito,
  # apenas el directorio ya cumplió su propósito (ver más abajo).
  trap 'rm -rf "$PEGASUS_TMPDIR"' EXIT

  info 'descargando pegasus y su checksum...'
  curl -fL -o "$PEGASUS_TMPDIR/pegasus" "$BASE_URL/pegasus" \
    || fallar 'no se pudo descargar pegasus'
  curl -fL -o "$PEGASUS_TMPDIR/pegasus.sha256" "$BASE_URL/pegasus.sha256" \
    || fallar 'no se pudo descargar pegasus.sha256'

  # sha256sum -c lee el basename adentro del archivo de checksum, por eso se
  # verifica parado en el mismo directorio donde cayeron los dos archivos.
  if ! (cd "$PEGASUS_TMPDIR" && sha256sum -c pegasus.sha256); then
    fallar 'el checksum de pegasus no coincide: los bytes descargados no son los que el release publica. Esto también puede pasar si se publicó un release nuevo entre las dos descargas; lo primero que hay que probar es volver a correr este script.'
  fi

  install -m 755 "$PEGASUS_TMPDIR/pegasus" "$BIN_DIR/pegasus" \
    || fallar 'no se pudo instalar el binario en su destino final'
  ok "pegasus instalado en $BIN_DIR/pegasus"

  # Limpieza explícita apenas el directorio ya cumplió su propósito -- ver el
  # comentario junto al trap, arriba: sin esto, cada corrida real (la que
  # termina en "exec pegasus" u "exec opencode") dejaba el directorio de la
  # descarga tirado en $TMPDIR para siempre.
  rm -rf "$PEGASUS_TMPDIR"
}

# Sólo ajusta el PATH de ESTE proceso -- para que, si esta misma corrida
# termina en "exec pegasus" más abajo, ese exec encuentre el binario recién
# instalado. No imprime nada: lo que la persona necesita leer sobre su PATH
# real (el de la terminal del otro lado del pipe, que este export no toca)
# lo imprime mostrar_guia_path, al final, no acá en el medio de la
# instalación.
asegurar_path() {
  detectar_path
  ((BIN_DIR_EN_PATH)) && return 0
  export PATH="$BIN_DIR:$PATH"
}

# --- Guía de PATH, al cierre ---
#
# Reemplaza el aviso que antes daba asegurar_path a mitad de instalación.
# Dos programas pueden haber quedado fuera del PATH de la terminal real
# (la que sigue viva del otro lado de un "curl ... | bash"): el binario de
# pegasus, en $BIN_DIR, y el de OpenCode, en $OPENCODE_BIN_DIR -- éste
# último lo instala el mecanismo oficial de OpenCode, que sólo agrega la
# línea a ~/.bashrc, igual que nvm hace con el suyo.
#
# Se nombra sólo el/los que de verdad aplican a esta corrida (lo que se
# instaló y, además, no estaba ya en el PATH con el que arrancó el script --
# ver ORIGINAL_PATH), y se da una sola línea "export PATH=..." que la
# persona puede pegar tal cual para arreglar la terminal actual. Se llama
# desde lanzar(), antes de decidir si hace exec o no -- si el script termina
# haciendo exec a una TUI, esto es lo último que la persona ve ANTES de esa
# TUI, no después: después de un exec no queda nada de este script para
# imprimir nada más.
# Cierra sobre dos hechos verificados contra /etc/skel en Debian/Ubuntu, que
# es lo que este instalador apunta:
#   - ~/.profile agrega ~/.local/bin al PATH, pero sólo si ese directorio YA
#     existía cuando la sesión arrancó -- justo lo que no pasa acá, porque
#     recién se acaba de crear.
#   - ~/.profile además hace `source` de ~/.bashrc (si la shell es bash) --
#     y es ~/.bashrc donde el instalador oficial de OpenCode dejó SU línea.
# Por eso "source ~/.profile" (no "source ~/.bashrc" a secas) es lo que
# arregla las dos cosas de una sola vez en la terminal actual: si alguien
# prueba sólo ~/.bashrc porque es lo primero que se le ocurre, opencode
# aparece pero pegasus sigue sin estar, y todo parece un instalador roto.
# No se ofrece como válido en todos lados: sólo cuando pegasus fue a parar
# al `~/.local/bin` de siempre -- con `--bin-dir` apuntando a otro lado,
# ~/.profile no tiene forma de saberlo, y el `export PATH=...` explícito es
# la única salida correcta.
mostrar_guia_path() {
  local falta_pegasus_dir=0 falta_opencode_dir=0
  ((FALTA_PEGASUS)) && ! dir_en_path "$ORIGINAL_PATH" "$BIN_DIR" && falta_pegasus_dir=1
  ((FALTA_OPENCODE)) && ! dir_en_path "$ORIGINAL_PATH" "$OPENCODE_BIN_DIR" && falta_opencode_dir=1
  ((falta_pegasus_dir || falta_opencode_dir)) || return 0

  titulo 'PATH'
  ((falta_pegasus_dir)) && info "pegasus, en $BIN_DIR: todavía no está en el PATH de esta terminal."
  ((falta_opencode_dir)) && info "opencode, en $OPENCODE_BIN_DIR: todavía no está en el PATH de esta terminal."

  local dirs=()
  ((falta_pegasus_dir)) && dirs+=("$BIN_DIR")
  ((falta_opencode_dir)) && dirs+=("$OPENCODE_BIN_DIR")
  local combinado export_linea
  combinado=$(IFS=:; printf '%s' "${dirs[*]}")
  export_linea="export PATH=\"$combinado:\$PATH\""

  if ((falta_pegasus_dir)) && [[ "$BIN_DIR" != "$HOME/.local/bin" ]]; then
    info "Para esta terminal: $export_linea"
  else
    info 'Para esta terminal: source ~/.profile'
    if ((falta_pegasus_dir && falta_opencode_dir)); then
      info '(no "source ~/.bashrc" sola: esa trae lo que instaló OpenCode, pero no'
      info 'agrega el bin de pegasus. ~/.profile hace las dos cosas: de paso vuelve'
      info 'a leer ~/.bashrc, y además agrega ~/.local/bin, que recién se creó.)'
    elif ((falta_pegasus_dir)); then
      info '(agrega ~/.local/bin al PATH, ahora que el directorio existe.)'
    else
      info '(vuelve a leer ~/.bashrc, donde quedó la línea que agregó el instalador'
      info 'de OpenCode.)'
    fi
    info "Si tu shell no lee ~/.profile (zsh, fish, ...): $export_linea"
  fi

  info 'Una sesión nueva ya la tiene sola, sin hacer nada de esto.'
}

# --- Qué queda corriendo al final ---
#
# Si esta corrida instaló algo de verdad, la persona todavía tiene que elegir
# MCPs y confirmar la instalación dentro de OpenCode: eso es lo que hace la
# TUI de pegasus. Si no hacía falta instalar nada, el entorno ya estaba
# listo, así que directamente se abre OpenCode para trabajar. Bajo --verify
# nunca se llega a instalar nada, así que ahí la decisión se proyecta a
# partir de lo que faltaría en una corrida real (FALTA_ALGO) en vez de a
# partir de lo que se hizo.
decidir_lanzamiento() {
  local se_instalo
  if [[ "$MODO" == 'verificar' ]]; then
    se_instalo=$FALTA_ALGO
  else
    se_instalo=$ALGO_SE_INSTALO
  fi

  if ((se_instalo)); then
    LANZAR='pegasus'
    MOTIVO='se instaló algo nuevo: todavía hay que elegir MCPs y confirmar la instalación en OpenCode'
  else
    LANZAR='opencode'
    MOTIVO='ya estaba todo instalado: el entorno está listo para trabajar'
  fi
}

lanzar() {
  decidir_lanzamiento

  # No bajo --verify: ahí nunca se instaló nada de verdad, así que no hay
  # ningún directorio "recién instalado" del que avisar todavía.
  [[ "$MODO" == 'verificar' ]] || mostrar_guia_path

  titulo 'Para terminar'

  if [[ "$MODO" == 'verificar' ]]; then
    info "se lanzaría: $LANZAR ($MOTIVO)"
    return 0
  fi
  if ((NO_RUN)); then
    info "no se lanza nada por --no-run. Se habría lanzado: $LANZAR ($MOTIVO)"
    return 0
  fi

  # $LANZAR (pegasus u opencode) es una TUI: sin una terminal real en su
  # stdin, abre, imprime su uso y sale -- ver el bug documentado en
  # hay_terminal_controladora. Bajo el "curl ... | bash" publicado, el
  # stdin de ESTE proceso es la tubería que bash ya drenó, no una terminal,
  # así que un "exec" liso que la heredara reproduciría exactamente eso.
  if hay_terminal_controladora; then
    info "lanzando $LANZAR ($MOTIVO)..."
    # exec reemplaza este proceso por el de destino en vez de encadenarlo:
    # así install.sh no queda colgado en el árbol de procesos esperando a
    # que termine, y no hay nada suyo pendiente por ejecutar después de
    # todos modos. "< /dev/tty" es lo que le da a pegasus/opencode una
    # terminal real en vez del stdin muerto de este proceso -- la terminal
    # de quien tipeó el comando sigue disponible ahí aunque este script
    # haya llegado por una tubería.
    exec "$LANZAR" < /dev/tty
  fi

  # Sin terminal controladora no hay a quién abrirle una TUI: exec'ear
  # igual sólo repetiría el bug (uso impreso, salida inmediata) sin que la
  # persona nunca vea el mensaje de arriba. La instalación en sí ya
  # terminó bien -- reportar esto como error confundiría un problema del
  # lanzamiento final con uno de la instalación, que no lo tuvo.
  info "no se lanza $LANZAR: no hay una terminal para abrirlo ($MOTIVO)."
  info "Corré esto para continuar: $LANZAR"
}

main() {
  parsear_argumentos "$@"
  rechazar_root
  detectar_todo
  calcular_faltantes
  calcular_bloqueo
  mostrar_preflight

  if [[ "$MODO" == 'verificar' ]]; then
    # El reporte ya se imprimió arriba, bloqueado o no. El código de salida es
    # lo único que falta: 0 si un run real podría avanzar, distinto de cero
    # si no — así "if install.sh --verify; then ..." sirve como chequeo. Si
    # está bloqueado no hay nada que lanzar ni fingir que se lanzaría.
    ((BLOQUEADO)) && exit 1
    lanzar
    exit 0
  fi

  ((BLOQUEADO)) && fallar_por_requisitos_bloqueantes

  # --no-run instala todo lo que falte igual que una corrida normal: la
  # única diferencia es el paso final, que no hace "exec" sino que informa
  # qué habría lanzado (ver lanzar). Antes --no-run no instalaba nada, lo
  # cual dejaba a quien seguía INSTALL_BY_AGENT.md creyendo que el entorno
  # había quedado listo cuando en realidad no se había tocado nada.
  if ((FALTA_ALGO)); then
    confirmar
    ((FALTA_NODE)) && instalar_node
    ((FALTA_OPENCODE)) && instalar_opencode
    ((FALTA_PEGASUS)) && instalar_pegasus
    asegurar_path
  fi

  lanzar
}

# Todo el trabajo vive arriba, adentro de funciones, y esta es la única línea
# suelta al nivel superior del archivo. Es a propósito: el uso previsto de
# este script es "curl ... | bash", y bash lee una tubería de a poco — un
# script con trabajo suelto en el nivel superior puede ejecutarse a medias si
# la conexión se corta a mitad de la descarga. Con todo adentro de funciones,
# bash ya tiene el archivo entero antes de que "main" corra una sola línea.
main "$@"

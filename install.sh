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
# A diferencia de fallar, no aborta: la usa escribir_path_rc, donde el resto
# de la instalación ya terminó bien y una falla acá es sólo cosmética (ver
# el comentario grande junto a esa función).
advertir() { printf 'ADVERTENCIA: %s\n' "$*" >&2; }
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
        BIN_DIR=$2
        # Un salto de línea no se puede representar de forma segura en una
        # sola línea de ningún archivo de configuración de shell, con
        # ninguno de los dos esquemas de comillas que usa escribir_path_rc
        # -- se corta acá, antes de instalar nada, en vez de descubrirlo
        # recién al escribir.
        case "$BIN_DIR" in
          *$'\n'*) fallar '--bin-dir no puede contener un salto de línea' ;;
        esac
        shift 2 ;;
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

# Qué shell corre esta persona y qué archivo de esa shell hay que tocar para
# agregarle el PATH -- se resuelve UNA sola vez acá, y tanto la persistencia
# real (ver escribir_path_rc) como el aviso de cierre (ver mostrar_guia_path)
# usan este mismo resultado, para que nunca puedan quedar en desacuerdo sobre
# qué archivo es "el" archivo de esta shell.
SHELL_NAME=''
SHELL_RC_FILE=''

detectar_shell() {
  local shell_path=''
  if [[ -n "${SHELL:-}" ]]; then
    shell_path="$SHELL"
  else
    # Sin $SHELL (pasa en algunos entornos sin login shell, o cuando algo la
    # borró del ambiente antes de invocar este script), se busca en NSS la
    # shell registrada para el usuario actual -- último campo de la línea de
    # passwd. Con `set -e` de por medio, un getent que no encuentra a nadie
    # (o que ni siquiera existe en este sistema) tiene que poder fallar sin
    # tirar abajo el script entero.
    local entrada_passwd=''
    entrada_passwd=$(getent passwd "$(id -un)" 2>/dev/null) || entrada_passwd=''
    shell_path="${entrada_passwd##*:}"
  fi

  # `${shell_path##*/}` en vez de `basename`: es el mismo resultado, pero sin
  # depender de un ejecutable externo que un PATH reducido a propósito (como
  # el de estos mismos tests) puede no tener.
  SHELL_NAME="${shell_path##*/}"
  [[ -n "$SHELL_NAME" ]] || SHELL_NAME='unknown'

  # Mismas listas de candidatos que usa el instalador oficial de OpenCode
  # (https://opencode.ai/install), a propósito: si algún día alguien corre
  # los dos instaladores en la misma cuenta, los dos coinciden en dónde vive
  # la línea de PATH de cada shell.
  local candidatos=()
  case "$SHELL_NAME" in
    fish)
      candidatos=("$HOME/.config/fish/config.fish")
      ;;
    zsh)
      local zdotdir="${ZDOTDIR:-$HOME}"
      local xdg_zsh="${XDG_CONFIG_HOME:-$HOME/.config}/zsh/.zshenv"
      candidatos=("$zdotdir/.zshrc" "$zdotdir/.zshenv" "$xdg_zsh")
      ;;
    bash)
      candidatos=("$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile")
      ;;
    sh|ash)
      candidatos=("$HOME/.ashrc" "$HOME/.profile" "/etc/profile")
      ;;
    *)
      candidatos=("$HOME/.profile")
      ;;
  esac

  SHELL_RC_FILE=''
  local candidato
  for candidato in "${candidatos[@]}"; do
    if [[ -f "$candidato" ]]; then
      SHELL_RC_FILE="$candidato"
      break
    fi
  done

  # Ninguno de los candidatos existe todavía: se elige el canónico de esa
  # shell, pero sin crearlo acá -- eso lo hace recién escribir_path_rc, en el
  # momento en que de verdad hay algo para escribirle (ver el comentario ahí).
  if [[ -z "$SHELL_RC_FILE" ]]; then
    case "$SHELL_NAME" in
      fish) SHELL_RC_FILE="$HOME/.config/fish/config.fish" ;;
      zsh)  SHELL_RC_FILE="$HOME/.zshrc" ;;
      bash) SHELL_RC_FILE="$HOME/.bashrc" ;;
      *)    SHELL_RC_FILE="$HOME/.profile" ;;
    esac
  fi
}

detectar_todo() {
  detectar_python
  detectar_curl
  detectar_node
  detectar_opencode
  detectar_pegasus
  detectar_path
  detectar_shell
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

# Si el directorio de pegasus y/o el de OpenCode van a faltar en el PATH de
# la terminal real que llamó a este script -- ver ORIGINAL_PATH, arriba, y
# por qué se compara contra ese valor y no contra el PATH ya modificado del
# propio proceso. Una sola función para que mostrar_guia_path y
# bloque_accion_requerida (ver más abajo) nunca puedan quedar en desacuerdo
# sobre si hay algo que avisar.
AVISO_PEGASUS_DIR=0
AVISO_OPENCODE_DIR=0

calcular_avisos_path() {
  AVISO_PEGASUS_DIR=0
  AVISO_OPENCODE_DIR=0
  ((FALTA_PEGASUS)) && ! dir_en_path "$ORIGINAL_PATH" "$BIN_DIR" && AVISO_PEGASUS_DIR=1
  ((FALTA_OPENCODE)) && ! dir_en_path "$ORIGINAL_PATH" "$OPENCODE_BIN_DIR" && AVISO_OPENCODE_DIR=1
  return 0
}

# Si además de avisar hay que escribir de verdad una línea de PATH en el
# archivo de la shell detectada. Se salta sólo en el caso en que Debian/Ubuntu
# ya resuelve esto solo: bash (o sh/ash, que en esa familia de distros leen lo
# mismo) con el BIN_DIR de siempre, porque ahí ~/.profile ya agrega
# ~/.local/bin en toda sesión nueva -- escribir ahí sería redundante. En
# cualquier otro caso (zsh, fish, shell desconocida, o un --bin-dir distinto
# del de siempre bajo cualquier shell) no hay nada más que lo resuelva solo.
PERSISTIR_PATH_RC=0
# shellcheck disable=SC2088 # es texto para mostrar tal cual, no un path que este script abra
RECOMENDACION_SOURCE='~/.profile'

# Si escribir_path_rc de verdad dejó la línea en el archivo -- ya sea porque
# la escribió esta corrida, o porque ya estaba de una corrida anterior. En 0
# cuando PERSISTIR_PATH_RC pidió persistir pero la escritura se degradó (rc
# file no escribible, o symlink rehusado): mostrar_guia_path y
# bloque_accion_requerida usan este valor para no afirmar "ya quedó
# agregada" cuando no es cierto.
PATH_RC_ESCRITO=0

# La línea que escribir_path_rc calculó para esta corrida (escrita o no):
# la guía de cierre degradada (ver mostrar_guia_path) la necesita para
# mostrarle a la persona el contenido exacto que tiene que agregar a mano
# cuando la escritura real no pudo hacerse.
LINEA_PATH_RC=''

calcular_persistencia_path() {
  local shell_ya_cubierta=0
  case "$SHELL_NAME" in
    bash|sh|ash)
      [[ "$BIN_DIR" == "$HOME/.local/bin" ]] && shell_ya_cubierta=1
      ;;
  esac

  if ((AVISO_PEGASUS_DIR)) && ! ((shell_ya_cubierta)); then
    PERSISTIR_PATH_RC=1
    RECOMENDACION_SOURCE="$SHELL_RC_FILE"
  else
    PERSISTIR_PATH_RC=0
    # shellcheck disable=SC2088 # idem: texto para mostrar, no un path a abrir
    RECOMENDACION_SOURCE='~/.profile'
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
  if ((PERSISTIR_PATH_RC)); then
    info "$BIN_DIR se agregará al PATH en $SHELL_RC_FILE"
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

# Deja agregada, en el archivo de la shell detectada (ver detectar_shell), la
# línea que pone a $BIN_DIR en el PATH -- para que una terminal NUEVA lo
# encuentre sola, sin que nadie tenga que acordarse de correr nada. Sólo se
# llama en una corrida real (nunca bajo --verify, que nunca instala nada de
# verdad), y sólo si calcular_persistencia_path decidió que hacía falta (ver
# ahí el porqué: bash/sh/ash con el BIN_DIR de siempre ya lo resuelve solo
# vía ~/.profile, y ahí escribir sería redundante).
#
# El archivo puede no existir todavía (candidato elegido por default, ver
# detectar_shell): recién acá, en el momento de escribir de verdad, se crea
# -- con su directorio padre si hace falta (~/.config/fish, por ejemplo,
# puede no existir en una cuenta nueva).
#
# Idempotente a propósito: si el archivo ya tiene, LITERAL Y EXACTA, la
# misma línea que este run escribiría, no se agrega nada de nuevo -- así
# correr el instalador dos veces no deja la línea duplicada. A propósito NO
# es un `grep` de substring: eso hacía "falso positivo" tanto con una
# mención en un comentario como con un directorio que sólo comparte prefijo
# (p.ej. BIN_DIR=".../bin" contra una línea que menciona ".../bin2"), y en
# los dos casos el script terminaba diciendo "ya quedó agregada" sin haber
# escrito nada de verdad.
#
# $BIN_DIR entra tal cual desde --bin-dir (ver parsear_argumentos): no hay
# ninguna garantía de que venga "limpio". Por eso se cita como un literal de
# comillas simples -- ni el shell que lea el rc file, ni el shell que corre
# ESTE script al construir la línea, vuelven a interpretar su contenido.
escapar_comilla_simple_posix() {
  # Regla estándar: se cierra la comilla, se escapa una comilla simple
  # literal por fuera de comillas, se reabre. Funciona igual para
  # bash/zsh/sh/ash: todos comparten esta regla de citado.
  printf '%s' "${1//\'/\'\\\'\'}"
}

escapar_comilla_simple_fish() {
  # La regla de fish DIFIERE de la de POSIX: adentro de comillas simples
  # sólo \ y ' son especiales (nada más lo es, a diferencia de POSIX donde
  # nada adentro de comillas simples lo es). La barra se escapa PRIMERO,
  # para que la barra que introduce el escape de la comilla no termine
  # reinterpretada ella misma.
  local valor="$1"
  valor="${valor//\\/\\\\}"
  valor="${valor//\'/\\\'}"
  printf '%s' "$valor"
}

escribir_path_rc() {
  ((PERSISTIR_PATH_RC)) || return 0

  # La línea se arma UNA sola vez, en una sola variable, y esa misma
  # variable es la que se usa tanto para el chequeo de idempotencia como
  # para la escritura -- así las dos no pueden divergir nunca.
  local linea
  if [[ "$SHELL_NAME" == 'fish' ]]; then
    linea="fish_add_path '$(escapar_comilla_simple_fish "$BIN_DIR")'"
  else
    # shellcheck disable=SC2016 # $PATH no debe expandir acá: es texto literal para el rc de la shell
    linea="export PATH='$(escapar_comilla_simple_posix "$BIN_DIR")':\"\$PATH\""
  fi
  LINEA_PATH_RC="$linea"

  # Un rc file simbólico es un caso legítimo (gestores de dotfiles suelen
  # symlinkear ~/.zshrc adentro de un repo) y un `>>` liso lo sigue solo,
  # escribiendo en el destino -- que es lo que se quiere. Lo que NO se
  # quiere es seguir ciegamente un symlink hacia cualquier lado: sólo se
  # rehúsa cuando el destino resuelto cae fuera de $HOME, o no es dueño de
  # él el usuario actual -- ahí se avisa y se degrada, igual que una
  # escritura fallida (ver más abajo).
  if [[ -L "$SHELL_RC_FILE" ]]; then
    local destino=''
    destino=$(realpath -m -- "$SHELL_RC_FILE" 2>/dev/null) || destino=''
    local fuera_de_home=1
    case "$destino" in
      "$HOME"|"$HOME"/*) fuera_de_home=0 ;;
    esac
    local dueno_ok=1
    if [[ -n "$destino" && -e "$destino" ]]; then
      [[ "$(stat -c '%u' -- "$destino" 2>/dev/null)" == "$(id -u)" ]] || dueno_ok=0
    fi
    if [[ -z "$destino" ]] || ((fuera_de_home)) || ! ((dueno_ok)); then
      advertir "$SHELL_RC_FILE es un symlink hacia afuera de \$HOME (o hacia algo que no es tuyo); no se va a tocar. Agregá esta línea a mano en el rc file real de tu shell:
$linea"
      return 0
    fi
  fi

  if ! mkdir -p "$(dirname "$SHELL_RC_FILE")" 2>/dev/null; then
    advertir "no se pudo crear $(dirname "$SHELL_RC_FILE"); vas a tener que agregar el PATH a mano. Línea a agregar:
$linea"
    return 0
  fi

  if [[ -f "$SHELL_RC_FILE" ]] && grep -qxF "$linea" "$SHELL_RC_FILE"; then
    PATH_RC_ESCRITO=1
    return 0
  fi

  if { printf '\n# pegasus-harness\n%s\n' "$linea"; } >> "$SHELL_RC_FILE" 2>/dev/null; then
    PATH_RC_ESCRITO=1
  else
    advertir "no se pudo escribir en $SHELL_RC_FILE; vas a tener que agregar el PATH a mano. Línea a agregar:
$linea"
  fi
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
# Ahora que detectar_shell (ver arriba) sabe qué shell corre esta persona y
# qué archivo de esa shell hay que tocar, esa detección reemplaza lo que
# antes era pura adivinanza: la rama de abajo distingue no ya "BIN_DIR es el
# de siempre o no", sino "esta corrida escribió una línea en un rc de verdad
# o no" (ver calcular_persistencia_path) -- si escribió, se nombra ESE
# archivo; si no (el caso bash/sh/ash con el BIN_DIR de siempre, que Debian ya
# resuelve solo), se deja el texto de siempre, palabra por palabra.
#
# Un límite que ninguna detección arregla: este script corre en un proceso
# chico (el que "curl | bash" lanzó), y ningún proceso hijo puede hacer
# `source` de un archivo adentro de la shell que lo invocó -- por más que acá
# adentro se sepa exactamente qué archivo es. Lo único que la detección
# compra es que el comando impreso sea el correcto para la shell real de la
# persona, y que el archivo que se nombra sea uno que esa shell de verdad lee
# -- no que este script pueda correrlo por ella.
# Calculado una sola vez, en una función compartida, para que
# mostrar_guia_path y bloque_accion_requerida (éste último en el caso
# degradado, ver ahí) nunca puedan imprimir un "export PATH=..." distinto
# entre sí.
EXPORT_LINEA=''

calcular_export_linea() {
  local dirs=()
  ((AVISO_PEGASUS_DIR)) && dirs+=("$BIN_DIR")
  ((AVISO_OPENCODE_DIR)) && dirs+=("$OPENCODE_BIN_DIR")
  local combinado
  combinado=$(IFS=:; printf '%s' "${dirs[*]}")
  EXPORT_LINEA="export PATH=\"$combinado:\$PATH\""
}

mostrar_guia_path() {
  calcular_avisos_path
  ((AVISO_PEGASUS_DIR || AVISO_OPENCODE_DIR)) || return 0
  calcular_export_linea

  titulo 'PATH'
  ((AVISO_PEGASUS_DIR)) && info "pegasus, en $BIN_DIR: todavía no está en el PATH de esta terminal."
  ((AVISO_OPENCODE_DIR)) && info "opencode, en $OPENCODE_BIN_DIR: todavía no está en el PATH de esta terminal."

  if ((PERSISTIR_PATH_RC)) && ((PATH_RC_ESCRITO)); then
    info "Para esta terminal: source $SHELL_RC_FILE"
    info "$EXPORT_LINEA"
    info 'Esa línea ya quedó agregada a ese archivo: una terminal nueva la toma'
    info 'sola, sin que haga falta correr nada de esto a mano.'
  elif ((PERSISTIR_PATH_RC)); then
    # escribir_path_rc no pudo dejar la línea (rc file no escribible, o un
    # symlink que se rehusó a seguir -- ver esa función): no hay ningún
    # archivo del que "una terminal nueva" vaya a leer nada solo, así que
    # acá no se afirma lo contrario. Se muestra la línea exacta para
    # agregar a mano, más el export de siempre para esta terminal.
    info "No se pudo dejar agregada la línea de PATH en $SHELL_RC_FILE."
    info 'Agregala vos a mano, con este contenido exacto:'
    info "$LINEA_PATH_RC"
    info "Para esta terminal: $EXPORT_LINEA"
  else
    info 'Para esta terminal: source ~/.profile'
    if ((AVISO_PEGASUS_DIR && AVISO_OPENCODE_DIR)); then
      info '(no "source ~/.bashrc" sola: esa trae lo que instaló OpenCode, pero no'
      info 'agrega el bin de pegasus. ~/.profile hace las dos cosas: de paso vuelve'
      info 'a leer ~/.bashrc, y además agrega ~/.local/bin, que recién se creó.)'
    elif ((AVISO_PEGASUS_DIR)); then
      info '(agrega ~/.local/bin al PATH, ahora que el directorio existe.)'
    else
      info '(vuelve a leer ~/.bashrc, donde quedó la línea que agregó el instalador'
      info 'de OpenCode.)'
    fi
    info "$EXPORT_LINEA"
    info 'Una sesión nueva ya la tiene sola, sin hacer nada de esto.'
  fi
}

# --- Recordatorio final, después de todo lo demás ---
#
# La sección "PATH" de arriba explica POR QUÉ hace falta hacer algo; este
# bloque es el recordatorio de que hay que hacerlo, y tiene que sobrevivir a
# que la TUI de pegasus/opencode tape la pantalla -- por eso se imprime como
# lo ÚLTIMO antes de que el control salga del script, en cada una de las tres
# salidas de lanzar() (exec, --no-run, y sin terminal controladora): cuando
# la persona cierra esa TUI y la consola vuelve a mostrarse, esto es lo que
# le queda arriba del prompt.
#
# Sin borde derecho a propósito: printf rellena por BYTES, no por
# caracteres, así que un `%-60s` con acentos ("sesión", "todavía") desalinea
# ese borde -- un recuadro cerrado se rompe visiblemente justo en el idioma
# que habla este script. Con sólo una raya arriba y otra abajo no hay borde
# derecho que alinear, así que no hay nada que romper.
bloque_accion_requerida() {
  calcular_avisos_path
  ((AVISO_PEGASUS_DIR || AVISO_OPENCODE_DIR)) || return 0

  # Sin `seq` ni ningún otro comando externo: este bloque existe justamente
  # para rescatar un PATH que todavía no sirve, y es lo último que se imprime
  # antes de soltar el control. Si se apoyara en coreutils, bajo
  # `set -euo pipefail` un PATH degradado mataría el script exactamente en el
  # aviso que iba a explicar cómo arreglar el PATH. Se rellena con espacios
  # (un byte cada uno) y recién después se sustituyen por la raya, para no
  # caer en el relleno por bytes que descarta la caja cerrada -- ver abajo.
  local raya
  printf -v raya '%*s' 62 ''
  raya=${raya// /─}

  printf '\n%s\n' "$raya"
  printf '  ANTES DE CORRER pegasus U opencode, en esta terminal:\n\n'
  if ((PERSISTIR_PATH_RC)) && ! ((PATH_RC_ESCRITO)); then
    # escribir_path_rc no pudo dejar la línea (ver mostrar_guia_path):
    # "source $SHELL_RC_FILE" no arreglaría nada, porque ese archivo no
    # tiene la línea. Se da el export de siempre, el que sí funciona ya
    # mismo en esta terminal.
    calcular_export_linea
    printf '      %s\n\n' "$EXPORT_LINEA"
    printf '  (no se pudo agregar la línea al archivo de tu shell; agregala vos a mano.)\n'
  else
    printf '      source %s\n\n' "$RECOMENDACION_SOURCE"
    printf '  Sin esto, esta terminal todavía no los encuentra.\n'
  fi
  printf '%s\n' "$raya"
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
    bloque_accion_requerida
    return 0
  fi

  # $LANZAR (pegasus u opencode) es una TUI: sin una terminal real en su
  # stdin, abre, imprime su uso y sale -- ver el bug documentado en
  # hay_terminal_controladora. Bajo el "curl ... | bash" publicado, el
  # stdin de ESTE proceso es la tubería que bash ya drenó, no una terminal,
  # así que un "exec" liso que la heredara reproduciría exactamente eso.
  if hay_terminal_controladora; then
    info "lanzando $LANZAR ($MOTIVO)..."
    bloque_accion_requerida
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
  bloque_accion_requerida
}

main() {
  parsear_argumentos "$@"
  rechazar_root
  detectar_todo
  calcular_faltantes
  calcular_avisos_path
  calcular_persistencia_path
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
    escribir_path_rc
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

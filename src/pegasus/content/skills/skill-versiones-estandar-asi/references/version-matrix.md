# ASI v6.4 Technology and Version Matrix

Use this matrix as the local decision source. "Homologated" means approved for new work. A listed version is the minimum accepted patch for that major.minor branch; later patches in that same branch are allowed only when they introduce no incompatibility or known vulnerability. Do not use a lower patch, a different minor branch, deprecated, or obsolete versions for new work.

If a technology has no exact version, a source conflict, or an approval requirement that is not already satisfied, stop and ask. Do not infer a version.

## Languages and Runtimes

| Technology | Homologated versions | Scope or exception | Provenance |
| --- | --- | --- | --- |
| PHP | 8.2.31; 8.3.31 | Use through an approved framework, not vanilla PHP. | ES0901 p.50; Changelog p.4 |
| Python | 3.12.13; 3.14.5 | Use through an approved framework, not vanilla Python. | ES0901 p.50; Changelog p.4 |
| Java (OpenJDK) | 17.0.19; 21.0.11 | Use through an approved framework. | ES0901 p.50; Changelog p.4 |
| TypeScript | 5.8.3; 5.9.3 | Use through an approved framework. | ES0901 p.50; Changelog p.4 |
| Node.js (JS/TS runtime) | 20.20.2; 22.22.2; 24.14.1 | Node 20 is support-only for existing applications. NPM is required; Yarn is prohibited. | ES0901 p.50, p.54; Changelog p.4 |
| Kotlin | 2.3.21 | Verify compatibility with the selected homologated Java version. | ES0901 p.50-51; Changelog p.4-5 |
| Swift | 6.2; 6.3 | Native mobile development only. | ES0901 p.50; Changelog p.4 |
| Dart | Coupled to Flutter | Select a homologated Flutter version. | ES0901 p.50 |

## Frameworks and Data Stores

| Technology | Homologated versions | Scope or exception | Provenance |
| --- | --- | --- | --- |
| Angular | 20.3.24 LTS; 21.2.16 |  | ES0901 p.51; Changelog p.4 |
| Next.js | 15.5.19; 16.2.7 |  | ES0901 p.51; Changelog p.4 |
| Ionic | 8.8.9 | Hybrid mobile requires prior ASI validation. | ES0901 p.51; Changelog p.4; ES0901 p.29 |
| Capacitor (runtime) | 8.3.0 | Hybrid mobile requires prior ASI validation. | ES0901 p.51; Changelog p.4; ES0901 p.29 |
| Flutter | 3.35.7; 3.41.9 |  | ES0901 p.51; Changelog p.4 |
| React Native | 0.84.0; 0.85.0 |  | ES0901 p.51; Changelog p.4 |
| NestJS | 10.4.22; 11.1.20 |  | ES0901 p.51; Changelog p.5 |
| Django | 5.2.15 LTS |  | ES0901 p.51; Changelog p.5 |
| FastAPI | 0.136.3 |  | ES0901 p.51; Changelog p.5 |
| Laravel | 12.60.0; 13.13.0 |  | ES0901 p.51; Changelog p.5 |
| Livewire | 3.8.1; 4.3.1 | Laravel only. | ES0901 p.51; Changelog p.5 |
| Express.js | 4.22.1; 5.2.1 |  | ES0901 p.51 |
| Fastify.js | 4.29.1; 5.8.5 |  | ES0901 p.51; Changelog p.5 |
| Spring Boot | 3.5.14 |  | ES0901 p.51; Changelog p.5 |
| .NET | 8.0.27 LTS; 10.0.8 LTS | Justify the platform choice. .NET 9 is only for an active application specifically dependent on that STS branch and with an LTS migration plan. | ES0901 p.51; Changelog p.5 |
| Oracle | 19c LTR | Validate the engine version with DGISIS and DGINFRA for new implementations. | ES0901 p.51 |
| PostgreSQL | 15.17 | Validate new engine choice with DGISIS and DGINFRA. Use only when required for PostGIS, packaged software without another option, multiple schemas, or inability to use Oracle/MariaDB; justify and review each case with DGINFRA. | ES0901 p.51-52; Changelog p.5 |
| MariaDB | 10.11 | Validate the engine version with DGISIS and DGINFRA for new implementations. | ES0901 p.51; Changelog p.5 |
| MongoDB | 8.0 | Validate the engine version with DGISIS and DGINFRA for new implementations. | ES0901 p.51 |
| Redis | 7.2 | Validate the engine version with DGISIS and DGINFRA for new implementations. | ES0901 p.51 |
| Apache Solr | 9.10.0 |  | ES0901 p.52 |
| Elastic Search | 8.17 |  | ES0901 p.52 |

## Android, Java, and Python Libraries

| Technology | Homologated versions | Scope or exception | Provenance |
| --- | --- | --- | --- |
| Android core | 1.17.0 |  | ES0901 p.52 |
| material-components | 1.13.0 |  | ES0901 p.52 |
| Maps | 19.2.0; 20.0.0 |  | ES0901 p.52; Changelog p.5 |
| Places | 4.4.1; 5.1.1 |  | ES0901 p.52; Changelog p.5 |
| Compose | 1.4.0; 1.5.15; 1.11.2 |  | ES0901 p.52; Changelog p.5 |
| Compose Navigation | 2.9.6 |  | ES0901 p.52 |
| WorkManager | 2.11.0 |  | ES0901 p.52 |
| RXJava3 | 3.1.11 |  | ES0901 p.52 |
| camerax | 1.6.1 |  | ES0901 p.52; Changelog p.5 |
| retrofit | 2.12.0; 3.0.0 |  | ES0901 p.52-53 |
| Okhttp | 5.3.2 |  | ES0901 p.52-53 |
| paging-runtime | 3.4.2 |  | ES0901 p.52; Changelog p.5 |
| lifecycle-livedata | 2.10.0 |  | ES0901 p.52 |
| hilt-android | 2.59.2 |  | ES0901 p.52; Changelog p.5 |
| room | 2.8.4 |  | ES0901 p.52 |
| Coil | 3.4.0 |  | ES0901 p.52; Changelog p.5 |
| lottie-android | 6.7.1 |  | ES0901 p.52 |
| Spring Cloud | 2025.0.2 |  | ES0901 p.53; Changelog p.6 |
| junit-jupiter-api | 5.14.2; 6.0.2 |  | ES0901 p.53 |
| modelmapper | 3.2.6 |  | ES0901 p.53 |
| Hibernate | 6.6.52 |  | ES0901 p.53; Changelog p.6 |
| ojdbc11 | 21.20.0; 23.26.0 |  | ES0901 p.53 |
| mockito-core | 5.21.0 |  | ES0901 p.53 |
| apache poi | 5.5.1 |  | ES0901 p.53 |
| aws-java-sdk-core | 2.46.2 |  | ES0901 p.53; Changelog p.6 |
| unirest-java-core | 4.8.1 |  | ES0901 p.53; Changelog p.6 |
| MapStruct | 1.6.3 |  | ES0901 p.53 |
| Gson | 2.13.2 |  | ES0901 p.53 |
| lombok | 1.18.42 |  | ES0901 p.53 |
| commons-codec | 1.20.0 |  | ES0901 p.53 |
| commons-lang3 | 3.20.0 |  | ES0901 p.53 |
| Matplotlib | 3.10.8 |  | ES0901 p.53 |
| Bokeh | 3.8.2 |  | ES0901 p.53 |
| NumPy | 2.4.1 |  | ES0901 p.53 |
| SciPy | 1.17.0 |  | ES0901 p.53 |
| SpaCy | 3.8.12 |  | ES0901 p.53; Changelog p.6 |
| Pandas | 2.3.3; 3.0.3 |  | ES0901 p.53; Changelog p.6 |
| PyTorch | 2.9.1 |  | ES0901 p.53 |
| NLTK | 3.9.4 |  | ES0901 p.53 |
| Gensim | 4.4.0 |  | ES0901 p.53 |
| transformers | 4.57.6; 5.2.10 |  | ES0901 p.53; Changelog p.6 |
| Pillow | 11.3.0; 12.2.0 |  | ES0901 p.53; Changelog p.6 |
| Scrapy | 2.16.0 |  | ES0901 p.53; Changelog p.6 |
| TensorFlow | 2.21.0 |  | ES0901 p.53; Changelog p.6 |
| Oracledb | 3.3.0; 4.0.1 | Only as a database connector through an approved framework and structured ORM such as SQLAlchemy. Direct use is prohibited. | ES0901 p.53-54; Changelog p.6 |
| mysql-connector-python | 9.5.0 | Only as a database connector through an approved framework and structured ORM such as SQLAlchemy. Direct use is prohibited. | ES0901 p.53-54 |

## Web and .NET Libraries, Design Systems

| Technology | Homologated versions | Scope or exception | Provenance |
| --- | --- | --- | --- |
| ngx-extended-pdf-viewer | 25.6.4; 27.0.0 |  | ES0901 p.54; Changelog p.6 |
| ngx-permissions | 19.0.0 |  | ES0901 p.54 |
| ngx-spinner | Per Angular version | Select only after matching the approved Angular version. | ES0901 p.54 |
| PrimeNg | 20.3.0; 21.1.8 |  | ES0901 p.54; Changelog p.6 |
| React | 18.3.1; 19.2.3 |  | ES0901 p.54 |
| React-Redux | 9.3.0 |  | ES0901 p.54; Changelog p.6 |
| @reduxjs/toolkit | 2.11.2 |  | ES0901 p.54 |
| Maps | 3.64 | JavaScript Maps library. | ES0901 p.54; Changelog p.6 |
| jwt-decode | 4.0.0 |  | ES0901 p.54 |
| Chart.js | 4.5.1 |  | ES0901 p.54 |
| Anime.js | 4.4.1 |  | ES0901 p.54; Changelog p.6 |
| Apache ECharts | 5.6.0; 6.1.0 |  | ES0901 p.54; Changelog p.6 |
| JOSE | 5.10.0; 6.1.3 |  | ES0901 p.54 |
| Openlayers.js | 9.2.4; 10.7.0 |  | ES0901 p.54 |
| Day.js | 1.11.19 |  | ES0901 p.54 |
| FullCalendar | 6.1.19 |  | ES0901 p.54 |
| helmet | 7.2.0; 8.1.0 |  | ES0901 p.54 |
| core-js | 3.48.0 |  | ES0901 p.54 |
| dotenv | 17.2.3 |  | ES0901 p.54 |
| express-fileupload | 1.5.2 |  | ES0901 p.54; Changelog p.6 |
| Underscore | 1.13.7 |  | ES0901 p.54 |
| Backbone.js | 1.6.1 |  | ES0901 p.54 |
| Quill | 2.0.3 | Approved rich-text editor. CKEditor 5 and TinyMCE require a technical-legal assessment. | ES0901 p.54-55 |
| three | 0.183.2 |  | ES0901 p.54; Changelog p.6 |
| Quartz.NET | 3.17.0 |  | ES0901 p.55; Changelog p.7 |
| NUnit | 4.6.1 |  | ES0901 p.55; Changelog p.7 |
| FluentValidation | 12.1.0 |  | ES0901 p.55 |
| NLog | 6.1.3 |  | ES0901 p.55; Changelog p.7 |
| Log4Net | 3.2.1 |  | ES0901 p.55 |
| MimeKit | 4.16.0 |  | ES0901 p.55; Changelog p.7 |
| Polly | 8.6.5 |  | ES0901 p.55 |
| Hangfire | 1.8.22 |  | ES0901 p.55 |
| Open CV | 4.13.0 |  | ES0901 p.55 |
| Libpng | 1.6.58 |  | ES0901 p.55; Changelog p.7 |
| Zlib-ng | 2.3.2 |  | ES0901 p.55 |
| Obelisco V2 | 1.8.4; 1.10.0 | Required design system; it uses Bootstrap. | ES0901 p.55; Changelog p.7 |
| Bootstrap | 5.3.8 | Used through Obelisco. | ES0901 p.55 |

## Platforms, Migrations, Infrastructure, and Security

| Technology | Homologated versions | Scope or exception | Provenance |
| --- | --- | --- | --- |
| WordPress | 6.8.3; 7.0.0 |  | ES0901 p.56; Changelog p.7 |
| Drupal | 10.6; 11.3 |  | ES0901 p.56 |
| Moodle | 4.5.12 LTS; 5.1.5 |  | ES0901 p.56; Changelog p.7 |
| CKAN | 2.10.10; 2.11.5 |  | ES0901 p.56; Changelog p.7 |
| GeoServer | 2.28.4 |  | ES0901 p.56; Changelog p.7 |
| Flyway | 11.20.3 |  | ES0901 p.56; Changelog p.8 |
| Laravel Migrations | Coupled to Laravel | Use the selected Laravel framework version. | ES0901 p.56 |
| Django Migrations | Coupled to Django | Use the selected Django framework version. | ES0901 p.56 |
| Entity Framework Core Migrations | Coupled to .NET | Use the selected .NET framework version. | ES0901 p.56 |
| Alembic | 1.18.4 |  | ES0901 p.56; Changelog p.8 |
| TypeORM | 0.3.30 |  | ES0901 p.56; Changelog p.8 |
| Sequelize Migrations | 6.37.8 |  | ES0901 p.56; Changelog p.8 |
| CIB Seven | 2.1.0 CE | Community Edition only. | ES0901 p.56; Changelog p.8 |
| Apache Kafka | 4.0 | Default message broker. | ES0901 p.57 |
| Apache ActiveMQ Artemis | 2.54.0 | Use only where its capabilities justify the scenario. | ES0901 p.57; Changelog p.8 |
| Apache Web Server | 2.4.x | Use the latest Red Hat-supported and certified release. Preferred web server. | ES0901 p.57 |
| Apache Tomcat | 10.1.55 |  | ES0901 p.57; Changelog p.8 |
| Nginx | 1.30.2 | Only where no other technically viable alternative exists. | ES0901 p.57; Changelog p.8 |
| JWS (JBoss Web Server) | 6.1; 6.2 |  | ES0901 p.57; Changelog p.8 |
| Varnish Cache | 6.0.13 | HTTP acceleration and web-content cache only. | ES0901 p.57; Changelog p.8 |
| RHEL | 8.7; 9.6 |  | ES0901 p.57 |
| Android | minSdkVersion 33 (Android 13) | Validate correct operation for the stated mobile OS scope. | ES0901 p.57; Changelog p.8 |
| iOS | Deployment Target iOS 18 | Validate correct operation for the stated mobile OS scope. | ES0901 p.57; Changelog p.8 |
| OpenSSL | 3.5 LTS |  | ES0901 p.58 |
| PrimeKey EJBCA | 9.3.6 |  | ES0901 p.58 |
| OpenID Connect (OIDC) | Provided by DGSEI | Ask DGSEI for the version for the specific use. | ES0901 p.58 |
| Keycloak | Provided by DGSEI | Ask DGSEI for the version for the specific use. | ES0901 p.58 |

## Explicitly Not Approved

| Technology | Rule | Provenance |
| --- | --- | --- |
| Yarn | Prohibited for Node.js dependency installation, administration, and execution. | ES0901 p.22, p.50, p.54 |
| Modernizr | Obsolete; use native JavaScript or build-system capabilities. | ES0901 p.54; Changelog p.6 |
| jQuery, jQuery UI, jQuery Migrate, jQuery Validation Plugin | Obsolete; do not add. | ES0901 p.54 |
| ApexCharts | Obsolete; use Apache ECharts where applicable. | ES0901 p.54; Changelog p.6 |
| ViewPager2 | Obsolete; use Compose. | ES0901 p.52; Changelog p.5 |
| NServiceBus | Removed because of its commercial licensing scheme. | Changelog p.7 |

## Source and Conflict Rules

- Primary source: organization-controlled ASI v6.4 standard, Annex II, pp. 48-58. The tables on pp. 50-58 define the homologated values. See `skill-versiones-estandar-asi/references/provenance.md` for the package-local distribution boundary.
- Change evidence: organization-controlled ASI v6.4 changelog, pp. 3-8. It states that it complements ES0901 and identifies v6.4 updates.
- The ASI standard requires approved frameworks rather than vanilla languages (ES0901 p.22), and toolchains are not individually homologated when compatible with approved platforms and ASI criteria (ES0901 p.19).
- If a source table, source note, or the two PDFs appears to contradict the value needed for a decision, do not resolve precedence by assumption. Stop and ask for an ASI decision.

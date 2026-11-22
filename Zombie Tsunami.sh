#!/bin/bash
# PORTMASTER: zombie-tsunami, Zombie Tsunami.sh
# Zombie Tsunami — loader nativo AArch64 (engine Mobi/cocos2d-x fork).
#
# BYO-APK: o jogador coloca o APK em gamedata/. O backend valida SHA-256,
# extrai com staging atomico e grava o marker; a UI do extrator mostra os
# estados. Nada de dado comercial e' distribuido com o port.

set -u

PORT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P) || exit 1
GAMEDIR="$PORT_DIR/zombie-tsunami"
TOOLS="$GAMEDIR/tools"
PAYLOAD="$GAMEDIR/payload"
LOGDIR="$GAMEDIR/logs"
LOADER="$GAMEDIR/bin/zombie-tsunami-loader"
BACKEND="$TOOLS/extractor/install.py"
UI="$TOOLS/extractor/extractor_ui"

mkdir -p "$LOGDIR" "$GAMEDIR/save" "$GAMEDIR/gamedata"

# Um arquivo por execucao: logs/run-NNN-AAAAMMDD-HHMMSS.log. O numero vem do
# maior existente + 1; o loader anexa no mesmo arquivo (ZT_LOG_FILE).
last_run=$(ls -1 "$LOGDIR"/run-*.log 2>/dev/null | sed 's|.*/run-||; s|-.*||' | sort -n | tail -1)
run_number=$(printf '%03d' $((10#${last_run:-0} + 1)))
run_stamp=$(date '+%Y%m%d-%H%M%S')
LOG="$LOGDIR/run-${run_number}-${run_stamp}.log"
export ZT_LOG_FILE="$LOG"
# Mantem as 20 execucoes mais recentes.
ls -1t "$LOGDIR"/run-*.log 2>/dev/null | tail -n +21 | while read -r old_log; do
  rm -f "$old_log"
done

log() { printf '%s\n' "$*" | tee -a "$LOG" >&2; }

finish() {
  local status=$?
  # Qualquer saida nao-zero deixa rastro: sem isso um abort antes do loader
  # aparece como "tela preta e fechou" sem nenhuma linha de erro no log.
  if [ "$status" -ne 0 ]; then
    log "ABORTOU com status $status (linha ${BASH_LINENO[0]:-?}, bash ${BASH_VERSION:-?})"
  fi
  if command -v pm_finish >/dev/null 2>&1; then pm_finish >/dev/null 2>&1 || true; fi
}
trap finish EXIT

# PortMaster: procuramos o control.txt nas raizes usadas pelos CFWs. Sourced
# apenas por variaveis de ambiente (CFW_NAME, ESUDO, paths). NAO chamamos
# get_controls: ele inicia o gptokeyb, que agarra o gamepad e injeta teclado —
# este port le o controle direto pelo SDL e pelo evdev.
PM_DIR=""
for candidate in \
    "/opt/system/Tools/PortMaster" \
    "/opt/tools/PortMaster" \
    "/roms/tools/PortMaster" \
    "/roms/ports/PortMaster" \
    "/roms2/ports/PortMaster" \
    "/storage/roms/ports/PortMaster" \
    "${XDG_DATA_HOME:-$HOME/.local/share}/PortMaster" \
    "$PORT_DIR/../PortMaster"; do
  if [ -f "$candidate/control.txt" ] && [ ! -L "$candidate/control.txt" ]; then
    PM_DIR=$candidate
    break
  fi
done

log "== zombie-tsunami =="
log "port=$PORT_DIR"
log "cfw=${CFW_NAME:-desconhecido}"

# Isola o runtime do guest do restante do firmware.
unset LD_PRELOAD LD_LIBRARY_PATH
unset SDL_VIDEO_EGL_DRIVER SDL_VIDEO_GL_DRIVER
unset PYTHONPATH PYTHONHOME

if [ -n "$PM_DIR" ]; then
  log "PortMaster: $PM_DIR"
  # control.txt/device_info.txt NAO foram escritos para `set -u`: qualquer
  # variavel nao definida neles derruba o shell inteiro (tela preta e saida
  # imediata). Por isso o `set +u` em volta do source.
  set +u
  # shellcheck disable=SC1090
  source "$PM_DIR/control.txt" 2>/dev/null || log "AVISO: falha no source de control.txt"
  if [ -f "$PM_DIR/device_info.txt" ]; then
    # device_info traz CFW_NAME/DEVICE_*/resolucao usados no log.
    source "$PM_DIR/device_info.txt" 2>/dev/null || log "AVISO: falha no source de device_info.txt"
  fi
  set -u
  # O control.txt exporta SDL_GAMECONTROLLERCONFIG_FILE apontando para um DB
  # montado por heuristica (/tmp/gamecontrollerdb.txt). No boot ele costuma
  # sair vazio e, em outras revisoes do pad, troca A/B. Ficamos com o mapping
  # embutido do SDL (validado no aparelho); o que falta vem do evdev cru.
  unset SDL_GAMECONTROLLERCONFIG_FILE
  log "cfw=${CFW_NAME:-desconhecido} device=${DEVICE_NAME:-desconhecido}"
  command -v pm_platform_helper >/dev/null 2>&1 && pm_platform_helper >/dev/null 2>&1 || true
fi

if [ ! -x "$LOADER" ]; then
  log "ERRO: loader ausente em $LOADER"
  exit 2
fi

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PYTHON=$candidate; break; fi
done
if [ -z "$PYTHON" ]; then
  log "ERRO: python3 nao encontrado; o instalador nao pode rodar neste firmware"
  exit 2
fi

needs_install() {
  local state
  state=$("$PYTHON" -u "$BACKEND" --check "$GAMEDIR" 2>&1 | tee -a "$LOG")
  case "$state" in
    INSTALLED*) return 1 ;;
    *) return 0 ;;
  esac
}

if needs_install; then
  log "payload ausente: abrindo instalador"
  if [ -x "$UI" ]; then
    "$UI" "$GAMEDIR"
    ui_status=$?
    log "extractor_ui terminou com status $ui_status"
  else
    "$PYTHON" -u "$BACKEND" --progress "$GAMEDIR" 2>&1 | tee -a "$LOG"
  fi
  if needs_install; then
    log "ERRO: dados do jogo nao instalados; o APK 4.5.133 precisa estar em gamedata/"
    exit 3
  fi
fi

# Bibliotecas do FMOD vem no pacote (Linux arm64), nunca do APK.
for lib in libfmod.so.13 libfmodstudio.so.13; do
  if [ -f "$GAMEDIR/lib/$lib" ] && [ ! -e "$PAYLOAD/$lib" ]; then
    cp -f "$GAMEDIR/lib/$lib" "$PAYLOAD/$lib" || log "AVISO: falha copiando $lib"
  fi
done
export ZT_GAMEDIR="$GAMEDIR"
export HOME="$GAMEDIR"
export XDG_CONFIG_HOME="$GAMEDIR/save"
export XDG_DATA_HOME="$GAMEDIR/save"
export TZ="${TZ:-UTC}"

cd "$GAMEDIR" || exit 2

log "iniciando loader"
"$LOADER" "$@"
status=$?
log "loader terminou com status $status"
exit "$status"

# Zombie Tsunami — Port for R36S

<p align="center"><img src="Zombie%20Tsunami.png" alt="Zombie Tsunami" width="640"/></p>

## English

Zombie Tsunami running on AArch64 Linux handhelds through a native loader for the original Android library, with GLES2, SDL2 and FMOD. The game uses a gamepad-controlled touch cursor.

The game APK and its data are not included. Device and firmware compatibility requires testing.

### Install

1. Download and extract the repository ZIP from **Code → Download ZIP**.
2. Copy `Zombie Tsunami.sh` and the `zombie-tsunami/` folder into your `ports/` folder.
3. Put your compatible APK in `ports/zombie-tsunami/gamedata/`. Any filename works.
4. Launch Zombie Tsunami from the ports menu. On first launch, the installer validates and extracts the game data. The original APK is preserved.

Requires AArch64 Linux, GLES2, SDL2, FreeType and Python 3. The package does not include a graphics driver or SDL2.

### Compatible APK

The installer accepts Zombie Tsunami **4.5.133**, versionCode **202**, package `net.mobigame.zombietsunami`, with 77,165,679 bytes and this SHA-256:

```text
6a4120730ccf9f1e1df03ad1144ba67b5615a99ad68c50fbcc875348c49dda49
```

`.apkm` and `.xapk` files containing this base APK are also accepted. Other versions or files with a different hash are rejected.

### Controls

| Input | Action |
|---|---|
| Left stick or D-pad | Move cursor |
| A, B, X, Y, L3 or R3 | Touch at cursor; hold to keep touching |
| Move while holding a button | Drag |
| Start | Touch upper-right corner, used to pause during gameplay |
| Select | Back |
| Select + Start | Exit |

The cursor disappears after three seconds without movement. During gameplay, touch is used to jump.

### Saves and troubleshooting

Saves are stored in `zombie-tsunami/save/`; the latest 20 run logs are kept in `zombie-tsunami/logs/`.

## Português

Zombie Tsunami para portáteis Linux AArch64, com um loader nativo para a biblioteca Android original, GLES2, SDL2 e FMOD. O gamepad controla um cursor de toque.

O APK e os dados do jogo não estão incluídos. A compatibilidade com dispositivos e firmwares precisa ser testada.

### Instalação

1. Baixe e extraia o ZIP do repositório em **Code → Download ZIP**.
2. Copie `Zombie Tsunami.sh` e a pasta `zombie-tsunami/` para a pasta `ports/`.
3. Coloque seu APK compatível em `ports/zombie-tsunami/gamedata/`. Qualquer nome de arquivo funciona.
4. Abra Zombie Tsunami no menu de ports. Na primeira execução, o instalador valida e extrai os dados do jogo. O APK original é preservado.

Requer Linux AArch64, GLES2, SDL2, FreeType e Python 3. O pacote não inclui driver gráfico nem SDL2.

### APK compatível

O instalador aceita Zombie Tsunami **4.5.133**, versionCode **202**, pacote `net.mobigame.zombietsunami`, com 77.165.679 bytes e este SHA-256:

```text
6a4120730ccf9f1e1df03ad1144ba67b5615a99ad68c50fbcc875348c49dda49
```

Também aceita arquivos `.apkm` e `.xapk` que contenham esse APK base. Outras versões ou arquivos com hash diferente são recusados.

### Controles

| Controle | Ação |
|---|---|
| Analógico esquerdo ou direcional | Move o cursor |
| A, B, X, Y, L3 ou R3 | Toca na posição do cursor; segure para manter o toque |
| Movimento com botão pressionado | Arrasta o toque |
| Start | Toca no canto superior direito, usado para pausar durante o jogo |
| Select | Voltar |
| Select + Start | Sair do port |

O cursor desaparece após três segundos sem movimento. Durante a partida, o toque é usado para pular.

### Saves e diagnóstico

Os saves ficam em `zombie-tsunami/save/`. Os logs das 20 execuções mais recentes ficam em `zombie-tsunami/logs/`.

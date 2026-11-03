# Changelog

Todas as mudanças importantes do Revelador ficam aqui. O formato segue o
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e as versões seguem o
[Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- Documentação para pessoas e agentes de IA: `AGENTS.md`, `CLAUDE.md` e `docs/ARQUITETURA.md` (receita única de
  prévia e exportação, tamanhos de revelação, enquadramento pelos rostos, ajustes, exportação, formato
  `.revelador`, atualização automática).
- Esqueleto do app: janela provisória e `--diagnostico`, que confere numpy, Pillow (JPEG com perfil sRGB e
  300 dpi), pillow-heif (HEIF), OpenCV (`cv2.FaceDetectorYN`) e Qt.
- Empacotamento do Windows: PyInstaller (`Revelador.spec`), instalador `.msi` por usuário (WiX 5) e `.zip`
  portátil com o marcador `revelador-install.json`; assinatura opcional.
- CI no GitHub Actions: testes em todo push; no `main`, executável com diagnóstico, `.msi` instalado, atualizado
  e desinstalado de verdade e `.zip`; release com `SHA256SUMS.txt` nas tags `v*`.
- Ícone do app (`assets/logo.svg`, gerado por `tools/gerar_icone.py`).
- Avisos do CI no Discord (`packaging/discord_notify.py`, segredo `DISCORD_WEBHOOK`): release publicada, falha
  no `main` e mensagem de teste pela execução manual.
- Previsão de custos da revelação planejada (`docs/ARQUITETURA.md`, seção 13; issue #13).

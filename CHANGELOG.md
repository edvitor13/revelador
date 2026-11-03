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
- Janela principal com áreas de grade, editor e painel lateral, tema que segue o claro/escuro do sistema,
  preferências e registro de erros em `%LOCALAPPDATA%\Revelador\logs` com aviso "Abrir registro" (#1).
- Abertura de fotos JPEG, PNG, HEIC/HEIF, WebP e TIFF com orientação EXIF, conversão de cor para sRGB e miniaturas
  em cache (núcleo; a grade vem depois) (#2).
- Tamanhos de revelação (14 prontos, de 9x13 a 40x60, e tamanho personalizado de 20 a 1000 mm) com px a 300 dpi e
  aviso de resolução boa, aceitável ou baixa (#3).
- Enquadramento automático pelos rostos (YuNet): cabeça inteira, grupos centralizados e margem de corte respeitada
  (#4).
- Ajustes de luz e cor: exposição, contraste, realces, sombras, brancos, pretos, temperatura, matiz, saturação,
  vibração e nitidez (núcleo; o painel vem depois) (#7).
- Salvar e abrir o trabalho (`.revelador`) com gravação segura, caminhos relativos e recuperação automática (#9).
- Atualização automática pelas releases do GitHub, só com SHA-256 conferido (núcleo; o diálogo vem depois) (#10).
- Previsão de custo por tamanho: valor por cópia em centavos, total estimado e aviso de total parcial quando falta
  preço (#13).
- Ferramenta `tools/previa_recortes.py` para conferir o enquadramento automático em fotos reais.

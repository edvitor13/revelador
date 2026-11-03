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
- Janela principal com áreas de grade, editor e painel lateral, tema escuro,
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
- Interface nova: tema escuro com cinzas neutros e o laranja do logo, barra superior (Importar, Projeto, Mostrar,
  tamanho padrão, custo do pedido, Exportar e engrenagem), painel lateral em cartões e ícones próprios.
- Importação e grade de fotos: arquivos, pastas ou arrastar e soltar, miniaturas em cache, fotos que não abrem
  marcadas com o motivo, rostos detectados em segundo plano (#2, #4).
- Seleção para revelação: marca na grade, filtro Todas | Selecionadas, tamanho e cópias de cada foto (a mesma foto em
  vários tamanhos, tamanho personalizado), tamanho padrão lembrado e total estimado do pedido na barra superior,
  com tabela de preços do laboratório e resumo por tamanho (#5, #13).
- Editor de enquadramento: moldura do papel, mover, zoom, girar 90°, endireitar, margem de corte, rostos, volta ao
  recorte automático e a visão "Resultado" igual ao que vai para o papel (#6).
- Painel de ajustes de luz, cor e detalhe com antes/depois (segure `\`), copiar e colar ajustes e restaurar; a
  prévia responde em cerca de 70 ms (#7).
- Exportar para revelação: uma pasta por tamanho, três modos de cópias, JPEG sRGB a 300 dpi com os pixels exatos,
  `pedido.txt` com o resumo e os valores, cancelamento sem deixar arquivos pela metade (#8).
- Salvar e abrir o trabalho: Projeto → Novo, Abrir, Recentes, Salvar e Salvar como, aviso ao fechar com mudanças,
  recuperação depois de uma falha, "Procurar…" para fotos que mudaram de lugar, abrir um `.revelador` pelo
  Explorer (associação opcional no instalador) (#9).
- Atualização automática: aviso com as novidades, "Instalar e reiniciar" ou "Pular esta versão"; a consulta é feita ao
  abrir, no máximo uma vez por dia, e pode ser desligada (#10).
- Ferramentas de desenvolvimento: `tools/captura_tela.py` (capturas da interface) e `tools/medir_ajustes.py`.
- Grade com o tamanho das miniaturas ajustável (controle "Miniaturas" no rodapé ou Ctrl + roda do mouse, de 80 a
  320 px, lembrado); em miniaturas pequenas o nome some e o chip mostra só as cópias. A grade abre com pelo menos
  duas colunas, inclusive para quem tinha a largura menor da primeira versão (#31).
- Orientação e cópias mais diretas: seletor Retrato | Paisagem que já mostra a orientação escolhida pela forma da foto
  (com "auto" e "Voltar ao automático"), botão "Girar papel" no painel e no editor (atalho `O`), botões − e + nas
  cópias, atalhos `+` e `−` e clique no chip da grade para somar uma cópia (Shift+clique tira uma) (#33).

# AGENTS.md — guia para quem mexe no código (pessoas e agentes de IA)

Este arquivo é a referência rápida para trabalhar no **Revelador**: o que o app faz, em que pé está, o que é cada
módulo, quais regras não podem ser quebradas, como rodar e testar, e receitas para as mudanças mais comuns. O
desenho técnico completo está em [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Em uma frase

App de desktop em Python (PySide6) para **escolher fotos e prepará-las para revelação** (impressão em laboratório):
cada foto escolhida recebe um tamanho de papel (10x15, 15x21, 20x30...), um **enquadramento na proporção exata do
papel** — no começo, centrado nos rostos —, ajustes básicos de luz e cor num painel lateral e sai como JPEG sRGB a
300 dpi numa **pasta por tamanho**, pronta para levar ou enviar ao laboratório. Só Windows por enquanto (o código
fica portável). Interface em português do Brasil.

### O problema que ele resolve

Fotos de celular e de câmera têm proporções que não batem com o papel (4:3, 16:9, 1:1 contra 2:3 do 10x15, 5:7 do
13x18...). Quando a foto vai assim para o laboratório, a máquina corta o que sobra pelo centro e muitas vezes corta
cabeças, pessoas na borda ou o assunto principal. O Revelador mostra exatamente o que vai sair no papel, sugere um
corte que preserva os rostos e deixa a pessoa ajustar antes de exportar — o laboratório recebe a foto já na
proporção certa e não precisa cortar nada além da margem de corte (sangria).

### Fluxo do usuário

1. **Importar** fotos (arquivos, pastas ou arrastar e soltar): JPEG, PNG, HEIC/HEIF (iPhone), WebP e TIFF.
2. **Selecionar** as que vão para revelação, escolher o **tamanho** e a **quantidade de cópias** de cada uma (uma
   foto pode sair em mais de um tamanho). Tamanho padrão: **10x15**.
3. **Conferir o enquadramento**: cada impressão já vem recortada na proporção do papel, centrada nos rostos; a
   pessoa move, aproxima, gira e endireita. Aviso de resolução baixa para o tamanho escolhido.
4. **Ajustar** a foto no painel lateral: exposição, contraste, realces, sombras, brancos, pretos, temperatura,
   matiz, saturação, vibração e nitidez, com antes/depois.
5. **Prever o custo**: com o valor base de cada tamanho (tabela de preços da pessoa), o app mostra o total estimado
   do pedido e o subtotal por tamanho, atualizado a cada mudança de seleção, tamanho ou cópias.
6. **Exportar para revelação**: uma pasta por tamanho, JPEG sRGB a 300 dpi com os px exatos do papel e um resumo
   do pedido (fotos, cópias e valores por tamanho).
7. **Salvar o trabalho** (`.revelador`) para continuar depois.

## Estado atual

Versão **0.1.0 em construção**. As fases A (núcleo), B (importação, grade, seleção, custo, editor) e C (ajustes,
exportação, salvar/abrir, atualização) e o **visual novo** estão no `main`. O que cada issue já tem:

- **#1, #2, #7, #8, #10, #13, #31, #33, #34, #35, #36: feitas** (fechadas). Ajustes com painel e prévia rápida,
  exportação com diálogo, atualização com diálogo e verificação ao abrir, preços e custo do pedido, tamanho das
  miniaturas da grade ajustável (#31), orientação Retrato | Paisagem explícita com "Girar papel" e cópias rápidas
  (#33), salvamento automático a cada minuto com Configurações (#34), tela de boas-vindas com recentes, novidades e
  atualizações (#35) e rostos aos poucos, com prioridade para a foto aberta e centro na média dos rostos (#36).
- **#3 (tamanhos)**: tabela, funções de px/qualidade e personalizado prontos e na interface (seletor, painel).
- **#4 (rostos)**: YuNet, política do recorte e detecção em segundo plano depois da importação.
- **#5 (seleção)**, **#6 (editor)**, **#9 (salvar/abrir)** e **#32 (pastas de tamanho)**: completas — desfazer/refazer (`QUndoStack`) de tudo o
  que a pessoa muda, menu de contexto da grade para aplicar tamanho e cópias a várias fotos e "Procurar…", alças nos
  cantos da moldura, ←/→ entre as fotos no editor, soltar um `.revelador` na janela e as pastas de tamanho (seção
  Pastas na grade com filtro, arrastar fotos para a pasta, chip na cor da pasta, passo de "Importar pasta",
  `.revelador` e exportação organizada por pasta).
- **#11 (release) e #12 (depois da 0.1.0)**: não começadas.

Outras pendências pequenas: miniatura da grade sem os ajustes, os títulos dos grupos no submenu "Tamanho ▸" da
grade e um aviso inofensivo do OpenCV no stderr. As funções
vieram pelas issues do marco **0.1.0**, nesta ordem sugerida:

| Issue | Assunto | Módulos |
|---|---|---|
| #1 | Fundação: janela principal, preferências, registro de erros, `_()` | `app.py`, `ui/`, `i18n.py`, `system.py`, `crashlog.py` |
| #2 | Importar fotos: miniaturas, orientação EXIF, sRGB | `imagem.py`, `miniaturas.py`, `ui/grade.py` |
| #3 | Tamanhos de revelação | `tamanhos.py` |
| #4 | Enquadramento automático pelos rostos | `rostos.py`, `enquadramento.py` |
| #5 | Seleção: marcar fotos, tamanho e cópias | `projeto.py` (modelo), `ui/grade.py` |
| #6 | Editor de enquadramento | `ui/editor.py`, `receita.py`, `enquadramento.py` |
| #7 | Ajustes no painel lateral | `ajustes.py`, `ui/painel_ajustes.py` |
| #8 | Exportar para revelação | `exportar.py`, `ui/exportar_dialog.py` |
| #13 | Previsão de custos: valor base por tamanho e total do pedido | `precos.py`, `ui/precos_dialog.py` |
| #9 | Salvar e abrir o trabalho (`.revelador`) | `projeto.py`, `ui/projeto_ui.py` |
| #10 | Atualização automática | `updater.py`, `ui/atualizacao.py` |
| #31 | Tamanho das miniaturas e duas colunas ao abrir | `ui/grade.py`, `ui/main_window.py` |
| #33 | Orientação explícita e botões rápidos de orientação e cópias | `ui/painel_impressoes.py`, `ui/editor.py` |
| #32 | Pastas de tamanho | `projeto.py`, `ui/estado.py`, `exportar.py`, `ui/pastas.py`, `ui/grade.py` |
| #34 | Salvamento automático | `ui/autosalvar.py`, `ui/configuracoes.py`, `ui/projeto_ui.py` |
| #35 | Tela de boas-vindas | `ui/boas_vindas.py`, `novidades/` |
| #36 | Rostos aos poucos e centro na média dos rostos | `ui/tarefas.py`, `enquadramento.py` |
| #11 | Roteiro da 0.1.0 (release) | — |

Ideias para depois da 0.1.0 ficam na issue #12. Antes de começar uma issue, leia a seção correspondente de
[docs/ARQUITETURA.md](docs/ARQUITETURA.md): ela é o contrato técnico.

## Mapa do código

Legenda: **[existe]** já está no repositório; **(#n)** chega com a issue *n* (hoje só a #11, o roteiro da release).

```
Revelador.pyw                 entrada sem console (pythonw); python -m revelador também funciona   [existe]
revelador/
  __init__.py                 __version__, __date__, APP_NAME                                        [existe]
  __main__.py                 python -m revelador                                                     [existe]
  app.py                      main(): --diagnostico, QApplication, janela, .revelador na linha de comando [existe]
  diagnostico.py              confere as dependências nativas de verdade (usado pelo CI no .exe)      [existe]
  i18n.py                     _() e N_(): por enquanto devolvem o texto; tradução depois            [existe]
  system.py                   open_path()/reveal() no explorador, pastas do usuário                  [existe]
  crashlog.py                 registro de erros não tratados em %LOCALAPPDATA%\Revelador\logs        [existe]
  imagem.py                   carregar (Pillow + pillow-heif), orientação EXIF, ICC → sRGB, proxy    [existe]
  miniaturas.py               cache de miniaturas em disco, chave (caminho, tamanho, mtime)          [existe]
  tamanhos.py                 TAMANHOS: tabela única dos tamanhos de revelação (mm, proporção, px)   [existe]
  rostos.py                   detecção de rostos com YuNet (cv2.FaceDetectorYN), modelo no pacote    [existe]
  enquadramento.py            geometria do recorte e recorte automático (funções puras)              [existe]
  ajustes.py                  PARAMS (esquema) e aplicar(): ajustes de luz e cor em numpy            [existe]
  receita.py                  receita única: renderizar(fonte, impressao, ajustes, destino_px) e geometria [existe]
  projeto.py                  modelo (Trabalho, Foto, Impressao, Recorte, Rosto) e .revelador         [existe]
  exportar.py                 pastas por tamanho, JPEG, cópias, pedido.txt, execução em paralelo     [existe]
  precos.py                   tabela de preços (centavos por tamanho) e orcamento() do pedido        [existe]
  updater.py                  atualização pelas releases do GitHub com SHA-256                       [existe]
  ui/
    main_window.py            janela: barra superior, áreas, contrato das ações acao_*, _ligar_<parte>() [existe]
    prefs.py                  settings(): única porta para as preferências (QSettings)               [existe]
    estado.py                 estado compartilhado da interface: os widgets conversam só por ele     [existe]
    desfazer.py               desfazer/refazer: fotografias, passos e junção de gestos (QUndoStack)  [existe]
    tema.py                   cores, medidas e folha de estilo (tema escuro neutro, destaque laranja) [existe]
    icones.py                 ícones vetoriais desenhados com QPainter                               [existe]
    componentes.py            Card, Slider, Segmented, ToggleSwitch, Pilula, BarraAdaptavel          [existe]
    grade.py                  grade de miniaturas, seleção, tamanho e cópias                         [existe]
    tarefas.py                importação em segundo plano: metadados, miniaturas e a fila de rostos  [existe]
    painel_impressoes.py      cartão Impressões e seletor de tamanho padrão                          [existe]
    pastas.py                 seção Pastas da grade, diálogo da pasta e passo de importar pasta      [existe]
    editor.py                 visor com a moldura do papel: mover, zoom, girar, endireitar, resultado [existe]
    previa.py                 trabalhadores do editor: proxy e prévia pela receita                   [existe]
    painel_ajustes.py         cartões Luz, Cor e Detalhe, gerados de ajustes.PARAMS                  [existe]
    exportar_dialog.py        diálogo de exportação e progresso                                      [existe]
    precos_dialog.py          tabela de preços por tamanho                                           [existe]
    resumo.py                 texto da barra de status e janela do resumo/custo do pedido            [existe]
    projeto_ui.py             Novo/Abrir/Salvar, recentes, título, recuperação, religar fotos        [existe]
    autosalvar.py             salvamento automático, nome e pasta automáticos, indicador de status   [existe]
    configuracoes.py          diálogo de Configurações em seções                                     [existe]
    boas_vindas.py            tela de boas-vindas: ações, recentes, recuperação, novidades, versão   [existe]
    atualizacao.py            verificação ao abrir e diálogo da atualização                          [existe]
  data/modelos/               face_detection_yunet_2023mar.onnx + LICENSE (MIT), SHA-256 em teste    [existe]
  novidades/release_vX.Y.Z.md notas da release (CI na tag) e "Novidades" da tela de boas-vindas    [existe]
packaging/
  install_marker.py           grava revelador-install.json {"kind": "msi"|"zip", "version"}          [existe]
  discord_notify.py           avisos do CI no Discord (release, falha, teste); só biblioteca padrão  [existe]
  windows/Revelador.wxs       instalador .msi (WiX 5), por usuário, UpgradeCode fixo                  [existe]
  windows/build_msi.ps1       monta o .msi                                                            [existe]
  windows/verificar_msi.ps1   CI: instala, confere, atualiza e desinstala o .msi de verdade           [existe]
  windows/diagnosticar.ps1    roda o --diagnostico de um Revelador.exe e confere o resultado         [existe]
  windows/assinar.ps1         assinatura opcional (só com certificado nos segredos)                  [existe]
  windows/license_rtf.py      LICENSE → .rtf da tela de licença do .msi                              [existe]
Revelador.spec                receita do PyInstaller (pasta única dist/Revelador)                    [existe]
tools/gerar_icone.py          assets/logo.svg → logo.ico e PNGs                                       [existe]
tools/previa_recortes.py      prévia do enquadramento automático em fotos reais (valida a política)   [existe]
tools/captura_tela.py         PNGs da janela, diálogos, menus e catálogo de componentes (revisão visual) [existe]
tools/medir_ajustes.py        tempo de ajustes.aplicar por ajuste e total, contra a referência lenta [existe]
tests/                        pytest; widgets do Qt só em subprocesso offscreen                       [existe]
tests/ajustes_referencia.py   versão lenta e simples dos ajustes, para comparar com a otimizada         [existe]
.github/workflows/build.yml   testes, pacotes Windows e release                                       [existe]
```

## Regras que não podem ser quebradas

1. **Originais intocáveis.** O app nunca grava, move, renomeia ou apaga a foto original, nem reescreve metadados
   dela. Tudo o que a pessoa faz vive no trabalho (`.revelador`) e na exportação. A exportação vai para uma pasta
   escolhida, nunca para a pasta da foto por padrão, e nunca sobrescreve um arquivo existente (nome livre com
   sufixo ` (2)`), gravando em arquivo temporário e renomeando no fim.
2. **Prévia e exportação usam o mesmo caminho.** Toda imagem mostrada (editor, antes/depois, miniatura ajustada) e
   toda imagem exportada passa pela **receita única** (`receita.py`): carregar → orientar (EXIF) → sRGB → giro de
   90°/endireitar → recorte → redimensionar para o tamanho de destino → ajustes → borda (modo *caber*). Quem chama
   só escolhe o tamanho de destino (prévia: o tamanho do visor; exportação: os px do papel) e de qual imagem parte
   (proxy ou original). Nunca implemente um ajuste ou um recorte só na interface ou só na exportação.
3. **Ajustes são funções puras e determinísticas.** `ajustes.aplicar(rgb, valores)` recebe numpy float32 em 0..1
   (H×W×3, sRGB) e devolve outro array; sem estado, sem cache escondido, sem `random`/`np.random`/`time`. Todo
   raio ou distância é **relativo ao tamanho da imagem de saída** (fração do lado menor) ou definido em **mm de
   papel** e convertido pelo dpi — assim a prévia pequena e a exportação grande ficam iguais.
4. **A proporção do papel é lei.** O recorte tem sempre exatamente a proporção do tamanho escolhido, na orientação
   da impressão; a exportação sai com os **px exatos** do papel (`round(mm / 25,4 × dpi)`). O recorte nunca sai
   da imagem (no modo *preencher*). Tamanhos só em `tamanhos.TAMANHOS`.
5. **Cor: sRGB na entrada e na saída.** Ao carregar, converta pelo perfil ICC embutido (Display P3 dos iPhones,
   Adobe RGB...) para sRGB com `PIL.ImageCms`; trabalhe em sRGB. Exporte JPEG com o perfil sRGB embutido, dpi
   gravado (300 por padrão), orientação EXIF já aplicada (sem tag de orientação), qualidade 95 e subamostragem
   4:4:4.
6. **O enquadramento automático é sugestão.** A detecção de rostos roda uma vez por foto (resultado guardado no
   trabalho) e só define o recorte inicial (`origem = "auto"`). Depois que a pessoa mexe, o recorte vira
   `"manual"` e nunca é refeito sozinho; trocar o tamanho reencaixa o recorte mantendo o centro e a escala
   possível. Sem rosto: centro (`"centro"`). Falha da detecção nunca impede importar nem exportar.
7. **Interface fluida.** Decodificar, gerar miniaturas, detectar rostos, calcular a prévia e exportar rodam fora da
   thread principal (`QThreadPool` ou threads com sinais); widgets do Qt só na thread principal. A prévia parte de
   uma cópia reduzida (proxy) e é recalculada com *debounce*; nunca decodifique o original inteiro a cada mexida
   de controle. Trabalho longo tem progresso e pode ser cancelado.
8. **Parâmetros novos com padrão neutro; IDs nunca mudam.** Chaves de ajustes (`ajustes.PARAMS`), IDs de tamanhos
   (`tamanhos.TAMANHOS`) e campos do `.revelador` ficam em português sem acento e não são renomeados nem removidos
   sem migração. Ajuste novo no padrão = foto idêntica.
9. **O `.revelador` é um formato público e versionado.** `projeto.FORMATO` é o maior formato que o app lê;
   formato antigo abre por passos de migração puros e testados; campo novo só é gravado quando usado; caminhos das
   fotos relativos ao arquivo quando possível (e absolutos como reserva); valores passam por `sanitize()`.
10. **Texto do usuário em PT-BR e sempre por `_()`.** Todo texto visível passa por `_()` (`from .i18n import _`)
    na hora de aparecer, com placeholders nomeados (`_("{n} cópias").format(n=...)`); tabelas montadas na
    importação usam `N_()`. Números com vírgula decimal na interface; tamanhos escritos como os laboratórios
    escrevem ("10x15", "15x21"). Identificadores, chaves e nomes de arquivos do código em português sem acento;
    docstrings e comentários em PT-BR.
11. **Dependências mínimas.** Em tempo de execução só **PySide6, numpy, Pillow, pillow-heif e
    opencv-python-headless** (OpenCV só para a detecção de rostos e redimensionamentos rápidos); o resto é
    biblioteca padrão. Nada de onnxruntime, PyTorch, MediaPipe, requests. O modelo de rostos (YuNet, licença MIT)
    vai dentro do pacote, com a licença ao lado e SHA-256 conferido por teste. Nada é baixado em tempo de
    execução, exceto as atualizações do próprio app.
12. **Atualizações só com SHA-256.** `updater.download()` exige o `SHA256SUMS.txt` da release e recusa arquivo que
    não confere. Os nomes dos pacotes (`Revelador-{tag}-windows-x64.msi` / `.zip`) precisam bater com os do CI, e
    cada pacote leva `revelador-install.json` com o tipo de instalação. O `UpgradeCode` do `.msi`
    (`E717D955-5229-48D9-BAF0-C0C95B783A82`) **nunca muda**.
13. **Windows primeiro, código portável.** Só o Windows é empacotado e testado no CI agora. Use `pathlib`,
    `system.open_path()`/`system.reveal()` em vez de `os.startfile`/`explorer`, e deixe o que for só do Windows
    atrás de `sys.platform == "win32"`; nada que impeça o Linux depois.
14. **Não sujar o ambiente do usuário.** Preferências só por `ui/prefs.settings()` (nunca `QSettings(...)`
    direto). Testes e automações definem `REVELADOR_SETTINGS_DIR` (preferências num `.ini` temporário) e
    `LOCALAPPDATA` (cache e registros) — a `conftest.py` faz isso — e nunca abrem nem gravam fotos fora de pastas
    temporárias. Widgets do Qt em teste só num subprocesso *offscreen* com `QApplication` própria.
15. **Fotos de pessoas são privadas.** Nada sai do computador: sem telemetria, sem envio de fotos, detecção de
    rostos local guardando só retângulos. Nenhuma foto pessoal entra no repositório: imagens de teste são geradas
    no código; a única exceção é foto em domínio público em `tests/data/`, registrada em `tests/data/LICENCAS.md`.

16. **Dinheiro em centavos inteiros.** Preços e totais são `int` em centavos (nunca `float`); a conversão de e para
    texto ("R$ 1.234,56", "1,50") fica só em `precos.formatar()`/`precos.ler()`. Tamanho sem preço é "sem preço" e
    deixa o total marcado como parcial — nunca vira zero calado. O valor é uma **estimativa** e a interface diz isso.
17. **Interface por um estado só.** Widgets não se conhecem: conversam apenas pelo `ui/estado.py` (`janela.estado`),
    mudam o modelo com `estado.alterar(...)` e reagem aos sinais. Cada parte se liga na `MainWindow` num método
    próprio `_ligar_<parte>()`, chamado no fim do `__init__`.

18. **Visual só pelo tema.** Nenhuma cor fixa (hexadecimal, `QColor("#...")`) nem `setStyleSheet` próprio fora de
    `ui/tema.py`: use as constantes e os nomes de objeto da folha de estilo (`Primary`, `Flat`, `Danger`, `Card`,
    `Muted`...), os componentes de `ui/componentes.py` e os ícones de `ui/icones.py`. Só tema escuro e cinzas neutros
    (a interface não pode tingir a percepção de cor da foto). Mexeu em tela? Rode `tools/captura_tela.py` (plataforma
    `windows`; `offscreen` não tem fontes) e **olhe o PNG** antes de entregar.
19. **Nada de rede em teste ou captura.** A verificação de atualização ao abrir não roda com a variável
    `REVELADOR_SEM_REDE` definida; testes e `captura_tela.py` a definem. Nenhum teste fala com a internet.

## Rodar

```bash
instalar.bat                      # cria .venv (py -3.15 → py -3) e instala requirements.txt
executar.bat [fotos...]           # .venv\Scripts\pythonw.exe Revelador.pyw
python -m revelador [fotos...]    # qualquer sistema, com as dependências instaladas
python -m revelador --diagnostico saida.json   # confere as dependências nativas e sai
```

Requisitos: Windows 10/11 x64, Python 3.12+ (recomendado **3.15**, o mesmo do CI). O `.venv` de referência usa
Python 3.15, PySide6 6.12, numpy 2.5, Pillow 13, pillow-heif 1.8 e OpenCV 5.0 (headless).

Variáveis de ambiente:

| Variável | Efeito |
|---|---|
| `REVELADOR_SETTINGS_DIR` | Preferências num `revelador.ini` nesta pasta em vez do registro (testes). |
| `REVELADOR_SEM_REDE` | Qualquer valor: não consulta atualizações ao abrir (testes e capturas de tela). |
| `REVELADOR_GITHUB_TOKEN` | Token para o atualizador consultar releases de um repositório privado (#10). |
| `QT_QPA_PLATFORM=offscreen` | Qt sem tela (CI, testes). Sem fontes reais no Windows: não use para capturas. |
| `LOCALAPPDATA` | Base do cache de miniaturas e dos registros (os testes redirecionam). |

## Testar

```bash
.venv\Scripts\python -m pytest -q
```

- Configuração em `pytest.ini` (`testpaths = tests`, `pythonpath = .`, sem cache).
- **Funções puras primeiro**: tamanhos, geometria do recorte, enquadramento automático (com rostos sintéticos em
  coordenadas), ajustes (padrão neutro = identidade; prévia pequena ≈ exportação grande), migrações do
  `.revelador`, nomes da exportação. Esses testes não precisam de Qt.
- **Imagens de teste geradas no código** (gradientes, cartelas, retângulos coloridos, JPEG com EXIF de orientação
  e perfil Display P3 montados com Pillow). Para a detecção de rostos, use só imagens com licença livre
  (domínio público/CC0) guardadas pequenas em `tests/data/` e registradas em `tests/data/LICENCAS.md`.
- **Interface**: casos *offscreen* num subprocesso com `QApplication` própria (veja `tests/test_app.py`); nunca
  crie `QApplication` no processo do pytest.
- **Exportação**: grave sempre em `tmp_path` e confira px, dpi, perfil ICC, ausência de orientação EXIF e que o
  original não mudou (SHA-256 antes e depois).
- `tests/test_empacotamento.py` protege o contrato do empacotamento (versão, marcador, `UpgradeCode`, nomes dos
  pacotes); `tests/test_diagnostico.py` roda o mesmo diagnóstico que o CI roda no executável.

## Receitas

### Adicionar um tamanho de revelação

1. Uma linha em `tamanhos.TAMANHOS`: `id` sem acento e **nunca renomeado** (`"10x15"`, `"a4"`), nome como o
   laboratório escreve, `lado_menor_mm` e `lado_maior_mm` (o tamanho real do papel; muitos são em polegadas:
   10x15 = 4×6 pol = 101,6 × 152,4 mm), grupo (comum, quadrado, ampliação).
2. A orientação vem da impressão (`"auto"` segue a foto); a tabela guarda sempre lado menor × lado maior.
3. Atualize a tabela de [docs/ARQUITETURA.md](docs/ARQUITETURA.md) (seção 4) e rode os testes de `tamanhos`
   (px a 300 dpi, proporção, IDs únicos).

### Adicionar um ajuste

1. Um `Param` em `ajustes.PARAMS` (chave sem acento, nome com `N_()`, mínimo, máximo, padrão neutro, grupo, passo).
2. A matemática em `ajustes.aplicar()`, na posição certa da ordem fixa (seção 7 da arquitetura). Raio/distância
   relativo ao tamanho da imagem.
3. O painel lateral é gerado do esquema: não crie controle à mão.
4. Testes: padrão = identidade (bit a bit em float32), monotonicidade, limites, e prévia reduzida ≈ exportação
   grande (diferença média pequena depois de reduzir a exportação ao tamanho da prévia).
5. Ajuste novo não precisa de migração do `.revelador` (chave ausente = padrão).

### Mudar o enquadramento automático

1. Detecção só em `rostos.py` (devolve retângulos e pontos dos olhos em coordenadas normalizadas da imagem
   orientada, com confiança); política do recorte só em `enquadramento.recorte_automatico()` (função pura).
2. Teste com rostos sintéticos (coordenadas) para cada caso: um rosto, grupo, rosto na borda, foto deitada,
   panorâmica, sem rosto. Mudança de política muda só recortes `"auto"` de fotos ainda não salvas; recortes já
   gravados no `.revelador` não são recalculados.

### Mudar o formato do `.revelador`

1. Campo novo opcional, gravado só quando usado: não precisa de formato novo.
2. Mudança que uma versão antiga entenderia errado: suba `projeto.FORMATO` e escreva um passo puro em
   `projeto.MIGRACOES` (formato n → n+1), com um arquivo de exemplo do formato antigo em `tests/data/` e teste.

### Gravar arquivos do usuário

- Use `projeto.gravar_texto_seguro()` (arquivo temporário na mesma pasta + `os.replace`)
  e o nome livre (` (2)`, ` (3)`...). Nunca grave na pasta da foto original sem a pessoa escolher, nunca
  sobrescreva sem perguntar, nunca apague nada que o app não criou.

### Adicionar uma dependência

- Evite. Se for inevitável: precisa ter roda (*wheel*) para Windows x64 e para a versão de Python do CI, licença
  compatível com MIT, funcionar dentro do PyInstaller (acrescente uma conferência real em `diagnostico.py`) e
  entrar em `requirements.txt`, `pyproject.toml`, na regra 11 deste arquivo e no `CLAUDE.md`.

## Empacotamento e release

### Pacotes

A pasta do PyInstaller (`dist/Revelador/`, com `Revelador.exe` e `_internal/`) é a base dos pacotes:

| Pacote | Como é montado | Onde instala | `kind` |
|---|---|---|---|
| `Revelador-{tag}-windows-x64.msi` | `packaging/windows/build_msi.ps1` (WiX 5) | `%LOCALAPPDATA%\Programs\Revelador` (por usuário, sem administrador) | `msi` |
| `Revelador-{tag}-windows-x64.zip` | `Compress-Archive` | onde a pessoa extrair | `zip` |

- **Marcador de instalação**: cada pacote leva `revelador-install.json` ao lado do executável, com
  `{"kind": ..., "version": "x.y.z"}`, gravado por `packaging/install_marker.py` na hora de montar **cada**
  pacote (o `.msi` e o `.zip` saem da mesma pasta: o marcador é regravado entre um e outro). O atualizador lê esse
  arquivo para escolher o pacote da release; os **nomes dos arquivos da release não podem mudar**.
- **`.msi`**: o `UpgradeCode` nunca muda — é ele que faz um `.msi` novo substituir o antigo no mesmo lugar
  (`MajorUpgrade`, inclusive na mesma versão). A pasta escolhida fica em `HKCU\Software\Revelador\InstallDir` e é
  reaproveitada nas atualizações. Recurso opcional: `AtalhoDesktop`. `ABRIR_APOS_INSTALAR=1` abre o app no fim de
  uma instalação silenciosa. Recurso opcional `AssociacaoRevelador` associa o `.revelador` ao app (só em `HKCU`). Versão do MSI: só `x.y.z`.
- **Conferências de verdade no CI**: `diagnosticar.ps1` roda `Revelador.exe --diagnostico` (codifica e decodifica
  JPEG com perfil e dpi, HEIF, redimensiona com OpenCV e confere `cv2.FaceDetectorYN`) no executável recém-gerado e
  no instalado; `verificar_msi.ps1` instala, confere, atualiza para uma versão maior (e numa pasta escolhida) e
  desinstala. **Não rode o `verificar_msi.ps1` no seu computador.**
- **Assinatura**: opcional, só com os segredos `WINDOWS_CERT_PFX_BASE64` e `WINDOWS_CERT_PASSWORD` (ou
  `WINDOWS_CERT_SHA1` no build local). Opções e custos: veja o `docs/ASSINATURA.md` do
  [PeliculaConverter](https://github.com/edvitor13/pelicula-converter/blob/main/docs/ASSINATURA.md), que usa o
  mesmo `assinar.ps1`.
- **Build local**: `build.bat` (o `.msi` só se o WiX estiver instalado:
  `dotnet tool install --global wix --version 5.0.2`).

### CI e Discord

- Todo push e PR: só o job `testes` (Windows). Os avisos no Discord usam o segredo `DISCORD_WEBHOOK` (nunca
  imprima nem grave em arquivo): âmbar quando uma release é publicada, vermelho quando um push no `main` falha;
  `gh workflow run build.yml -f testar_discord=true` manda só uma mensagem de teste.
- Push no `main`, tags `v*` e `workflow_dispatch`: o job `build` também gera o executável, roda o diagnóstico,
  monta e testa o `.msi`, monta o `.zip` e envia os dois como artefatos. Para validar uma branch:
  `gh workflow run build.yml --ref <branch>`.
- Tags `v*`: release com os pacotes e o `SHA256SUMS.txt`. O texto vem de `revelador/novidades/release_{tag}.md`
  (as primeiras linhas, até uma linha `---`, viram o resumo do aviso no Discord); sem o arquivo, o GitHub gera as
  notas. A tag precisa bater com `revelador.__version__` (o build falha se não
  bater). Tag com `-` (ex.: `v0.1.0-beta.1`) vira pre-release, que o atualizador ignora.
- Linux e macOS ficam para depois (#12): o `build.yml` só tem Windows de propósito.

### Versão e release

1. Atualize `revelador/__init__.py` (`__version__` e `__date__`; o `pyproject.toml` e o `Revelador.spec` leem a
   versão de lá), o `CHANGELOG.md` (a seção "Não lançado" vira `[X.Y.Z] - data`) e escreva
   `revelador/novidades/release_vX.Y.Z.md`.
2. Valide a branch com `gh workflow run build.yml --ref <branch>` (pacotes completos).
3. Crie a tag `vX.Y.Z` e envie. O workflow gera os pacotes, publica a Release e avisa no Discord. Release só quando
   o autor pedir.

## Fluxo de trabalho

- Uma issue por vez, numa branch (`issue-<n>-<assunto>`), com PR para o `main`; merge só com o CI verde.
- Commits em PT-BR, no imperativo ou descritivos, com a issue no fim: `Tamanhos de revelação: tabela e px a 300
  dpi (#3)`.
- Ao terminar uma issue: testes novos passando, documentação atualizada (este arquivo, a arquitetura e o
  `CHANGELOG.md` em "Não lançado") e o mapa do código acima sem a marca "(#n)" do que passou a existir.

## Estilo

- Python 3.12+, `from __future__ import annotations`, tipagem moderna (`X | None`), `dataclass`, linhas de até
  ~120 colunas.
- Mensagens ao usuário curtas, diretas e em PT-BR; números com vírgula decimal.
- Nada de mídia pessoal no repositório (veja o `.gitignore`); capturas de tela da documentação só com imagens
  geradas ou de licença livre.

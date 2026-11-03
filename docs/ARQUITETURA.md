# Arquitetura do Revelador

Contrato técnico do app. Cada issue do marco 0.1.0 implementa uma ou mais seções daqui; quando a implementação
mostrar que algo precisa mudar, mude **este arquivo junto** no mesmo PR. Regras gerais e receitas em
[AGENTS.md](../AGENTS.md).

Sumário: 1. Visão geral · 2. Modelo de dados · 3. Carregar fotos · 4. Tamanhos de revelação · 5. Enquadramento ·
6. Receita única · 7. Ajustes · 8. Exportação · 9. Formato `.revelador` · 10. Interface · 11. Atualização
automática · 12. Empacotamento · 13. Custos da revelação

---

## 1. Visão geral

```
  arquivos/pastas ──► imagem.carregar ──► proxy (≤ 2048 px) ──► miniaturas (cache em disco)
                         │  EXIF, ICC→sRGB        │
                         │                        └──► rostos.detectar ──► enquadramento.recorte_automatico
                         ▼                                                         │
                   original (só na exportação)                                     ▼
                                                    Trabalho ─ Foto ─ Impressao(tamanho, cópias, Recorte)
                                                                 └ ajustes {chave: valor}
                                                                          │
                     ┌────────────────────── receita.renderizar ◄─────────┘
                     │   giro 90° → recorte/endireitar → redimensionar → ajustes → borda
                     ▼
        prévia (proxy, tamanho do visor)            exportação (original, px exatos do papel)
                                                      └► JPEG sRGB 300 dpi em <destino>/<tamanho>/
```

- **Um caminho só** do pixel original até a imagem final (`receita.py`); a prévia e a exportação diferem apenas
  na fonte (proxy ou original) e no tamanho de destino.
- **Tudo o que a pessoa decide** (seleção, tamanhos, cópias, recortes, ajustes) é dado puro no modelo
  (`projeto.py`), gravável no `.revelador`, e nunca muda o arquivo original.
- **Trabalho pesado fora da thread principal** (decodificar, miniaturas, rostos, prévia, exportação).

## 2. Modelo de dados

`projeto.py` (dataclasses; JSON na seção 9):

```python
@dataclass
class Rosto:                 # coordenadas normalizadas (0..1) da imagem ORIENTADA (EXIF aplicado, sem giro)
    x: float; y: float; w: float; h: float
    olhos: tuple[tuple[float, float], tuple[float, float]] | None
    confianca: float

@dataclass
class Recorte:
    cx: float = 0.5          # centro, normalizado à imagem orientada E girada (giro aplicado)
    cy: float = 0.5
    zoom: float = 1.0        # 1 = maior recorte possível nessa proporção; 2 = metade da largura...
    angulo: float = 0.0      # endireitar, graus, -45..45, em torno do centro do recorte
    giro: int = 0            # giros de 90° no sentido horário (0..3), sem perda
    origem: str = "auto"     # "auto" (rostos) | "centro" (sem rosto) | "manual" (a pessoa mexeu)

@dataclass
class Impressao:
    tamanho: str = "10x15"   # id de tamanhos.TAMANHOS
    copias: int = 1
    orientacao: str = "auto" # "auto" (segue a foto) | "retrato" | "paisagem"
    modo: str = "preencher"  # "preencher" (corta na proporção) | "caber" (foto inteira com borda branca)
    recorte: Recorte = field(default_factory=Recorte)
    papel_mm: tuple[float, float] | None = None  # só no tamanho "personalizado" (seção 4)
    preco_centavos: int | None = None            # só no personalizado: valor por cópia (seção 13)
    pasta: str | None = None # id da Pasta de tamanho de onde veio; None = impressão avulsa

@dataclass
class Pasta:                 # pasta de tamanho (#32): grupo virtual do trabalho, nada muda no disco
    id: str                  # "p" + 11 hexadecimais, nunca muda
    nome: str
    cor: str                 # chave da paleta de ui/tema.py (CORES_PASTA), não um hexadecimal
    tamanho: str = "10x15"   # o tamanho de TODAS as impressões da pasta
    copias: int = 1          # cópias das impressões novas
    papel_mm: tuple[float, float] | None = None  # só no personalizado
    preco_centavos: int | None = None            # só no personalizado

@dataclass
class Foto:
    id: str                  # estável dentro do trabalho
    caminho: Path
    bytes: int; mtime: float # para avisar se o arquivo mudou ou sumiu
    selecionada: bool = False
    ajustes: dict[str, float] = field(default_factory=dict)   # só chaves fora do padrão
    rostos: list[Rosto] | None = None                         # None = ainda não detectado; [] = nenhum
    impressoes: list[Impressao] = field(default_factory=list) # vazia até ser selecionada

@dataclass
class Trabalho:
    fotos: list[Foto]
    tamanho_padrao: str = "10x15"
    dpi: int = 300
    margem_corte_mm: float = 2.0
    caminho: Path | None = None  # o .revelador, quando salvo
    pastas: list[Pasta] = field(default_factory=list)  # na ordem da tela
```

- Os **ajustes são da foto** (valem para todas as impressões dela); o **recorte é da impressão** (cada papel tem
  a sua proporção). Selecionar uma foto cria uma impressão no tamanho padrão com o recorte automático.
- **Pastas de tamanho** (#32): estar numa pasta = ter **uma** impressão com `pasta = <id>`, no tamanho (e no papel e
  preço do personalizado) da pasta; a foto pode estar em várias pastas e ainda ter impressões avulsas. Cópias,
  orientação, modo e recorte continuam por foto. Mudar o tamanho da pasta muda as impressões dela (recorte automático
  refeito, manual reencaixado); mudar as cópias da pasta só atualiza as impressões que ainda tinham as cópias antigas
  dela; tirar a foto da pasta remove aquela impressão e, sem nenhuma sobrando, a foto deixa de estar marcada; apagar a
  pasta tira só as impressões dela. Ao entrar numa pasta, uma impressão avulsa do mesmo tamanho vira a da pasta
  (mantém cópias e recorte), em vez de a foto sair revelada duas vezes; uma foto desmarcada descarta as avulsas que
  guardava e entra só no tamanho da pasta. Tudo pela API do `Estado` (seção 10), nunca mexendo nas listas à mão.
- **Desfazer/refazer** (#5, `ui/desfazer.py`): um `QUndoStack` por trabalho (`Estado.pilha`). O `Estado` guarda uma
  *fotografia* do que é editável em cada foto (`selecionada`, `impressoes`, `ajustes`) e de `trabalho.pastas`;
  `alterar`, `alterar_pastas` e `remover` comparam com ela e empilham o antes/depois. Entram marcar/desmarcar,
  impressões (tamanho, cópias, orientação, modo, adicionar/remover), recortes, ajustes, pastas e tirar fotos do
  trabalho (desfazer põe a foto de volta no mesmo lugar, com metadados e miniatura). Mudanças do sistema (importação,
  metadados, rostos, trabalho aberto) não viram passo: só atualizam a fotografia (`absorver`). Ao desfazer, os
  recortes automáticos são recalculados com os metadados e rostos do momento; um passo de uma foto só a torna a atual.
  Trocar de trabalho limpa a pilha; desfazer sempre marca o trabalho como modificado. Detalhes da junção de gestos na
  seção 10.

## 3. Carregar fotos

`imagem.py`:

- **Formatos**: JPEG, PNG, HEIC/HEIF (`pillow_heif.register_heif_opener()`, uma vez), WebP, TIFF. RAW fica para
  depois (#12). Arquivo que não abre vira item com aviso, nunca derruba a importação.
- **Orientação**: a tag EXIF é aplicada por `transpose` **depois** da redução e da conversão de cor (equivale ao
  `ImageOps.exif_transpose`, mas barato). Daí em diante, "imagem orientada" é a base de todas as coordenadas.
- **Cor**: se houver `icc_profile`, `ImageCms.profileToProfile(..., srgb, renderingIntent=RELATIVE_COLORIMETRIC,
  flags=BLACKPOINTCOMPENSATION, outputMode="RGB")`; sem perfil, assume sRGB. Perfil inválido ou não suportado também
  é tratado como sRGB, e perfil com "sRGB" no nome pula a conversão. CMYK com perfil converte pelo perfil;
  transparência é composta sobre **branco** (cor do papel). Tons de cinza viram RGB.
- **Proxy**: cópia com lado maior ≤ 2048 px para a prévia e a detecção de rostos. Para JPEG use
  `Image.draft("RGB", ...)` (decodificação reduzida pelo DCT), que é várias vezes mais rápida. Cache em memória
  (LRU por bytes, ~512 MB). `proxy()` devolve um array **somente leitura e compartilhado**: copie antes de alterar.
- **Miniaturas** (`miniaturas.py`): lado maior 320 px, JPEG q85 em
  `%LOCALAPPDATA%\Revelador\cache\miniaturas\<sha1(caminho|bytes|mtime)>.jpg`; limpeza LRU acima de 500 MB.
  Geradas num `QThreadPool` na ordem em que aparecem na tela. Fora do Windows o cache fica em
  `$XDG_CACHE_HOME/Revelador/cache` (ou `~/.cache`).
- **Metadados** (`InfoFoto`): tamanho em px (orientado), data original (EXIF `DateTimeOriginal`) para ordenar,
  modelo da câmera, nome do perfil, bytes e `mtime`. `InfoFoto.mtime` é `st_mtime_ns` (inteiro); `Foto.mtime`
  segue em segundos e o `Estado` converte. Nada é escrito de volta no arquivo.
- **Original para exportação**: o mesmo carregamento sem redução, em float32 0..1.

## 4. Tamanhos de revelação

`tamanhos.py` guarda a tabela única. O tamanho real do papel manda (muitos tamanhos "em cm" são polegadas); a
coluna de px é a 300 dpi (`round(mm / 25,4 × dpi)`). IDs sem acento e **nunca renomeados**.

| id | Nome | Papel (mm) | Origem | Proporção | px a 300 dpi | Grupo |
|---|---|---|---|---|---|---|
| `9x13` | 9x13 | 88,9 × 127 | 3,5×5 pol | 1,43 (≈ 7:10) | 1050 × 1500 | comum |
| `10x15` | 10x15 | 101,6 × 152,4 | 4×6 pol | 1,5 (2:3) | 1200 × 1800 | comum (**padrão**) |
| `13x18` | 13x18 | 127 × 177,8 | 5×7 pol | 1,4 (5:7) | 1500 × 2100 | comum |
| `15x20` | 15x20 | 152,4 × 203,2 | 6×8 pol | 1,33 (3:4) | 1800 × 2400 | comum |
| `15x21` | 15x21 | 152,4 × 210 | papel de 6 pol × 21 cm | 1,38 | 1800 × 2480 | comum |
| `20x25` | 20x25 | 203,2 × 254 | 8×10 pol | 1,25 (4:5) | 2400 × 3000 | ampliação |
| `20x30` | 20x30 | 203,2 × 304,8 | 8×12 pol | 1,5 (2:3) | 2400 × 3600 | ampliação |
| `a4` | A4 (21x29,7) | 210 × 297 | ISO 216 | 1,41 (1:√2) | 2480 × 3508 | ampliação |
| `30x40` | 30x40 | 304,8 × 406,4 | 12×16 pol | 1,33 (3:4) | 3600 × 4800 | ampliação |
| `30x45` | 30x45 | 304,8 × 457,2 | 12×18 pol | 1,5 (2:3) | 3600 × 5400 | ampliação |
| `40x60` | 40x60 | 406,4 × 609,6 | 16×24 pol | 1,5 (2:3) | 4800 × 7200 | ampliação |
| `10x10` | 10x10 | 101,6 × 101,6 | 4×4 pol | 1 | 1200 × 1200 | quadrado |
| `15x15` | 15x15 | 152,4 × 152,4 | 6×6 pol | 1 | 1800 × 1800 | quadrado |
| `20x20` | 20x20 | 203,2 × 203,2 | 8×8 pol | 1 | 2400 × 2400 | quadrado |

- **`obter(id)`** só atende os 14 tamanhos da tabela. O personalizado passa por `papel_mm(id, papel_mm)`,
  `proporcao(id, orientacao, papel_mm)` e `px(id, orientacao, dpi, papel_mm)`; cada lado vale de 20 a 1000 mm.
- **Personalizado**: largura × altura em cm digitados pela pessoa, gravados na impressão
  (`"tamanho": "personalizado"`, `"papel_mm": [w, h]`), com o valor por cópia opcional junto
  (`"preco_centavos"`, seção 13).
- Os tamanhos variam um pouco entre laboratórios (principalmente o 15x21): a tabela é a referência do app e a
  documentação para o usuário deve dizer para confirmar com o laboratório.
- **dpi**: 300 por padrão (opção 240–400 por trabalho).
- **Resolução efetiva** de uma impressão = px do recorte na foto original ÷ polegadas do papel. ≥ 200 dpi: boa;
  150–199: aceitável (aviso discreto); < 150: baixa (aviso visível na grade, no editor e antes de exportar).
  `qualidade(dpi)` devolve as chaves `"boa"`, `"aceitavel"` e `"baixa"`.
- **Orientação**: `"auto"` usa retrato se a imagem (já girada) for mais alta que larga, paisagem se não; papel
  quadrado ignora. A proporção usada no recorte é `lado_menor/lado_maior` (retrato) ou o inverso (paisagem).
- **Margem de corte** (sangria): o laboratório apara ~1–3 mm por lado. O editor mostra a área segura
  (`margem_corte_mm`, 2 mm por padrão) e o recorte automático evita pôr rostos ali.

## 5. Enquadramento

### 5.1 Geometria (`enquadramento.py`, funções puras)

Imagem orientada e girada com `W × H` px; proporção do papel `r = largura/altura` (na orientação da impressão).

- **Maior recorte sem rotação**: se `W/H > r`, `h₀ = H, w₀ = H·r`; senão `w₀ = W, h₀ = W/r`. Com zoom:
  `w = w₀/zoom`, `h = h₀/zoom` (`zoom ≥ 1` no modo *preencher*).
- **Com endireitar (ângulo θ)**: o recorte girado cabe na imagem se a caixa envolvente cabe:
  `w·|cos θ| + h·|sin θ| ≤ W` e `w·|sin θ| + h·|cos θ| ≤ H`. Daí o maior `w` possível; o zoom efetivo nunca deixa
  o recorte sair da imagem (sem cantos vazios).
- **Centro**: `(cx·W, cy·H)`, limitado para a caixa envolvente ficar dentro da imagem.
- `retangulo(recorte, W, H, r) → (cx, cy, w, h, θ)` em px é a única função que transforma o `Recorte` em
  geometria; o editor, a receita e os testes usam ela.
- **Trocar tamanho/orientação**: mantém `cx, cy, zoom, θ` e recalcula; recorte `"auto"` é refeito pelos rostos.
- **O recorte é da foto**: cada `Impressao` guarda o seu `Recorte` (o arquivo não muda), mas mexer no recorte de uma
  copia `cx, cy, zoom, θ, giro` para todas as impressões da foto, cada uma reencaixada na proporção do próprio papel
  (`Estado.compartilhar_recorte`); uma impressão nova herda o recorte manual (`refazer_recortes_auto`). Para ter
  outro recorte, a pessoa duplica a foto ("Duplicar foto", mesmo arquivo, id novo). "Centralizar" grava o maior
  recorte no centro como `"manual"`.
- **Giro de 90°** muda `W × H` e a orientação automática; rostos são transformados para o espaço girado na hora
  de usar (ficam gravados no espaço sem giro).

### 5.2 Recorte automático pelos rostos

Detecção (`rostos.py`): **YuNet** (`face_detection_yunet_2023mar.onnx`, do opencv_zoo, licença MIT, ~230 KB) por
`cv2.FaceDetectorYN.create(modelo, "", (w, h), score_threshold=0.6, nms_threshold=0.3, top_k=100)`, sobre o
proxy reduzido a lado maior 1280 px. Devolve `Rosto` normalizado (caixa, olhos, confiança). Descarta rostos com
largura < 1,5% do lado menor da imagem. Roda uma vez por foto, num trabalhador, e o resultado vai para
`Foto.rostos`.

**Aos poucos** (#36, `ui/tarefas.FilaRostos`, em `Importacao.rostos`): a detecção tem um `QThreadPool` só dela com
`limite_rostos()` trabalhadores (1; 2 em máquinas com 8 núcleos ou mais). A fila fica na thread principal e entrega ao
pool uma foto por trabalhador livre, escolhida na hora: (a) as pedidas (`Estado.pedir_rostos`, usado por "Enquadrar
pelos rostos" numa foto sem detecção), a foto atual e as recém-marcadas para revelar, que furam a fila e não esperam
as miniaturas; (b) depois que as miniaturas terminam, as fotos visíveis no viewport da grade (`Estado.na_tela`,
publicadas com espera de 150 ms); (c) a ordem da grade (`Estado.visiveis`) e o resto. Pausa enquanto a exportação
roda (`Estado.exportando`, avisado pelo diálogo). Progresso discreto na barra de status ("Rostos: 12 de 80"), que
volta a "Pronto." no fim. Rostos já guardados no `.revelador` não são detectados de novo; foto alterada no disco
(`bytes`/`mtime` diferentes dos guardados) volta a `rostos = None` em `definir_info` e é detectada de novo. Foto que
não abre para a detecção não é tentada de novo sozinha (só se for religada ou pedida pelo editor).

Política (`enquadramento.recorte_automatico(W, H, proporcao, rostos, margem=0.0) → Recorte`, pura):

1. **Sem rostos** → centro (`cx = cy = 0,5`, `zoom = 1`, `origem = "centro"`).
2. **Importância** de cada rosto = área × confiança. **Principais** = rostos com importância ≥ 15% da maior
   (`PRINCIPAL`; tira gente pequena ao fundo).
3. **Região de interesse (ROI)** = união das caixas principais **expandidas**. Há três expansões
   (`EXPANSOES`, em fração da altura do rosto para cima e para baixo e da largura para os lados): 0,60 / 0,35 /
   0,30 (a folgada), 0,45 / 0,20 / 0,15 e 0,35 / 0,10 / 0,05 (a mais justa, que ainda inclui o topo da cabeça).
4. **Antes de descartar um rosto**, tenta as expansões nessa ordem, cada uma primeiro com a margem de corte e
   depois sem ela. `margem` é a fração do lado menor do papel (2 mm num 10x15 = 2/102): quando há folga, nenhum
   rosto fica dentro dela.
5. Recorte com `zoom = 1` (o maior recorte, sem ângulo) na proporção do papel.
6. **Horizontal**: centraliza na **média simples dos centros dos rostos principais** (#36: todos contam igual, como
   o autor pediu), mantendo a ROI inteira dentro do recorte (cabeças inteiras). A confiança só conta no limite
   `PRINCIPAL`, que continua tirando os rostos pequenos ou de fundo.
7. **Vertical**: põe a linha dos olhos (média ponderada pela importância; sem pontos dos olhos, 40% da altura da
   caixa) a 1/3 do topo do recorte; depois garante o topo da ROI dentro (cabeça nunca cortada) e, se couber, a
   base também.
8. Se a ROI não couber nem com a expansão mais justa, **descarta** um rosto principal e repete. Entre os
   **empatados** (importância até 1,25× a menor, `EMPATE`) sai o mais distante do centro do grupo (a média simples
   dos centros; o da ponta).
   Com um rosto só e maior que o papel, centra nele e prioriza o topo da cabeça.
9. Limita à imagem. `origem = "auto"` e `giro = 0` (quem chama põe o giro da impressão).

- **`recorte_sugerido(impressao, largura, altura, rostos, margem_corte_mm=0.0) → Recorte`** é o **caminho único da
  interface** (ao selecionar, ao trocar tamanho ou orientação de uma impressão não manual, quando chegam os rostos).
  Recebe a imagem orientada **sem giro**, aplica o giro da impressão (`girar_rostos`), resolve a orientação e a
  proporção, converte a margem de mm para fração do lado menor do papel e chama `recorte_automatico`, mantendo o
  giro. Quem chama só substitui o recorte quando `origem != "manual"`.
- **Funções auxiliares** de `enquadramento.py`: `tamanho_maximo(W, H, proporcao, angulo=0)` (maior `w × h` que
  girado cabe na imagem), `caixa_envolvente(w, h, angulo)` e `zoom_efetivo(recorte, W, H, proporcao)` (o zoom de
  fato aplicado; endireitar só aproxima quando precisa, senão o recorte mantém a escala do zoom pedido).
- **Modelo** (`rostos.py`): lido uma vez para a memória e passado como buffer ao OpenCV (caminhos com acento no
  Windows quebram a leitura por caminho); `criar_detector(largura, altura)` cria o `cv2.FaceDetectorYN` (um por
  thread, pois ele não é seguro entre threads); o SHA-256 do arquivo é fixo e conferido por teste
  (`sha256_modelo()`). O OpenCV 5 escreve um aviso inofensivo no stderr ao criar o detector. `detectar(rgb)` nunca
  lança: falha vira lista vazia e registro no `logging`.
- `tools/previa_recortes.py` gera, para uma pasta de fotos reais, JPEGs reduzidos com o recorte automático em pé e
  deitado, para validar a política a olho.

Casos de teste obrigatórios (rostos sintéticos em coordenadas): retrato com um rosto em foto 4:3 deitada para
10x15 em pé; grupo em linha numa foto 16:9 para 10x15 deitado; rosto encostado na borda; selfie com rosto
grande; criança pequena + adulto grande; panorâmica 3:1; foto quadrada; sem rosto.

## 6. Receita única

`receita.renderizar(fonte, impressao, ajustes, destino_px) → np.ndarray` (float32 0..1, H×W×3, sRGB). `fonte` é a
imagem já orientada e em sRGB (seção 3); `ajustes` é o dicionário da foto (ou `None`); `destino_px` é `(largura,
altura)`. A escala mm/px (para a nitidez) é calculada **dentro**, a partir do papel da impressão e do destino
(`escala_mm_px`). O módulo é puro (sem Qt) e tem as peças que o editor e a exportação compartilham:

- `carregar_fonte(caminho, "original" | "proxy")`: a fonte orientada/sRGB (`"proxy"` para a prévia, `"original"`
  para a exportação); `para_uint8(img)`: arredondamento simples, determinístico.
- `tamanho_exportacao(impressao, largura, altura, dpi=300)`: os px exatos do papel na orientação da impressão;
  `destino_na_caixa(impressao, largura, altura, caixa_w, caixa_h)`: a maior imagem com a proporção do papel dentro
  do visor. `largura`/`altura` são sempre as da imagem orientada **sem giro** (`InfoFoto` ou `fonte.shape`).
- Geometria (usada também pelo editor, para desenhar exatamente o que a receita vai amostrar):
  `retangulo_da_impressao`, `matriz_destino_fonte(ret, dw, dh)`, `poligono(ret)`, `encolher(ret, margem)` (margem
  de corte), `ponto_da_fonte`, `dimensoes_giradas`, `orientacao`, `proporcao`, `papel_orientado_mm`, `girar`.

Passos:

1. **Giro de 90°** (`recorte.giro`, sentido horário): `np.rot90` (sem perda).
2. **Recorte + endireitar + redimensionar numa transformação afim só**: `enquadramento.retangulo` dá o retângulo
   (centro, tamanho, ângulo) na imagem girada e **uma única** `cv2.warpAffine` (`INTER_LANCZOS4`, borda replicada)
   amostra do destino para a fonte com `matriz_destino_fonte`. Quando a redução é grande, a região que interessa
   é reduzida antes com `INTER_AREA` (sem serrilhado), até ~1 px de fonte por px de destino.
3. **Ajustes** (`ajustes.aplicar`) já no tamanho de destino, com a escala em px por mm de papel.
4. **Modo *caber***: a foto inteira (só o giro; **ângulo e zoom são ignorados**) centralizada sobre papel branco nos
   px exatos do destino; os ajustes valem só para a foto, não para a borda.
5. Saída: para a tela, `para_uint8` → `QImage`; para a exportação, `para_uint8` → JPEG.

- **Convenção do ângulo**: `angulo > 0` gira a **foto** no sentido horário no resultado (o retângulo do recorte
  gira no sentido anti-horário sobre a imagem).
- `destino_px` da exportação = `tamanho_exportacao` (px exatos do papel, seção 4). Da prévia = `destino_na_caixa`
  do visor × `devicePixelRatio`.
- A prévia roda num trabalhador (`ui/previa.py`) com contador de geração (resultado velho é descartado) e
  *debounce* de ~60 ms; arrastar o recorte mostra a imagem já calculada transformada pelo Qt e recalcula ao soltar.

## 7. Ajustes

`ajustes.PARAMS` (esquema; o painel lateral é gerado dele) e `ajustes.aplicar(rgb, valores, escala_mm_px=None)`
(pura). São **11 ajustes**, todos de -100 a 100 com padrão 0 (nitidez: 0 a 100). **Padrão = identidade exata.** A
ordem do painel (`PARAMS`: exposição, contraste, realces, sombras, brancos, pretos, temperatura, matiz, saturação,
vibração, nitidez) **não é** a ordem de aplicação; esta é fixa em `aplicar()`:

| Ordem | Chave | Nome | Grupo | Efeito |
|---|---|---|---|---|
| 1 | `temperatura` | Temperatura | Cor | ganhos R/B em luz linear, luminância preservada (mais quente/mais fria) |
| 1 | `matiz` | Matiz | Cor | ganho G em luz linear (verde ↔ magenta) |
| 2 | `exposicao` | Exposição | Luz | `× 2^(v/50)` em luz linear (±2 EV) |
| 3 | `brancos` | Brancos | Luz | move o ponto branco da curva de tons |
| 3 | `pretos` | Pretos | Luz | move o ponto preto da curva de tons |
| 4 | `realces` | Realces | Luz | curva nas luzes altas, máscara pela luminância suavizada (negativo recupera céu) |
| 4 | `sombras` | Sombras | Luz | curva nas luzes baixas, máscara pela luminância suavizada (positivo abre sombras) |
| 5 | `contraste` | Contraste | Luz | curva em S suave em torno do cinza médio, preservando 0 e 1 |
| 6 | `saturacao` | Saturação | Cor | croma × (1 + v/100) em OKLCh (−100 = preto e branco) |
| 6 | `vibracao` | Vibração | Cor | aumenta mais a croma das cores pouco saturadas, atenuando na faixa de tons de pele |
| 7 | `nitidez` | Nitidez | Detalhe | máscara de nitidez na luminância (OKLab L), raio em mm de papel, com limiar contra ruído |

- **Luz linear**: decodifique sRGB → linear para temperatura, matiz e exposição; volte para sRGB para as curvas.
- **Realces/sombras**: a máscara usa a luminância desfocada com sigma = **2% do lado menor** da imagem de destino
  (relativo: a prévia e a exportação ficam iguais). Sem halos visíveis: misture com a luminância nítida.
- **Nitidez**: raio de 0,1 mm de papel (≈ 1,2 px a 300 dpi), convertido para a escala da prévia; quantidade até
  1,5× na ponta; aplicada por último, no tamanho final.
- Sem cortes duros: toda curva é suave e o resultado é limitado a 0..1 só no fim.
- **Fórmulas finais** (`t = v/100`; valores negativos viram 0 antes de luz linear ou OKLab):
  1. Temperatura e matiz em luz linear: `gR = 2^(0,4·t_temp)`, `gB = 2^(−0,4·t_temp)`, `gG = 2^(−0,3·t_matiz)`,
     divididos por `0,2126·gR + 0,7152·gG + 0,0722·gB` (a luminância do branco se mantém).
  2. Exposição em luz linear: `× 2^(v/50)` (±2 EV), na mesma multiplicação do passo 1.
  3. Brancos e pretos (sRGB): `y += 0,2·t_brancos·x²` e `y += 0,15·t_pretos·(1−x)²`.
  4. Guia `G = 0,75·desfoque(Y) + 0,25·Y` (sigma 2% do lado menor, numa cópia reduzida a sigma ≈ 4 px e ampliada);
     `Mr = smoothstep(0,45; 1; G)`, `Ms = 1 − smoothstep(0; 0,55; G)`. Realces: `RGB × (1 + 0,4·t·Mr)`.
     Sombras: `RGB^(1 − 0,6·t·Ms)` por canal.
  5. Contraste: `y = x + t·x(1−x)(2x−1)`.
  6. OKLab, `a` e `b` × `Fs·Fv`: `Fs = 1 + t_sat`; `p = (1 − min(C/0,3; 1))²`; `pele = ((1 + cos(h − 55°))/2)^8`;
     `Fv = 1 + t·p·(1 − 0,75·pele)` se positivo, `1 + t·(0,3 + 0,7·(1−p))·(1 − 0,75·pele)` se negativo.
  7. Nitidez em `L` (OKLab): `L' = L + 1,5·t·d·d²/(d²+0,01²)`, `d = L − gaussiana(L)`, sigma = 0,1 mm ×
     `escala_mm_px` (sem ela, 1/1000 do lado menor).
- **Desempenho**: ~65–76 ms numa prévia de 1600 × 1067 com tudo ligado (antes ~440–580 ms), com tabelas de
  consulta para sRGB↔linear, `cv2.remap` nas curvas e raízes LMS no lugar de `pow`. `tests/ajustes_referencia.py`
  guarda a versão lenta de referência (os testes comparam contra ela) e `tools/medir_ajustes.py [--referencia]` mede o
  tempo por ajuste e com tudo ligado. O mesmo código roda na exportação. Durante o arraste de um controle o editor
  usa uma **prévia reduzida** (lado maior de 640 px, `LADO_RAPIDO`) e refaz no tamanho final ao parar.
- **Copiar/colar ajustes** entre fotos (Ctrl+Shift+C / Ctrl+Shift+V; colar vale para a foto atual ou para todas as
  escolhidas na grade) e **Redefinir** (por ajuste com duplo clique no controle, por grupo e tudo). **Antes/depois**:
  mesmo recorte sem ajustes, enquanto `\` está pressionada ou pelo botão (`estado.comparando`).
- Depois da 0.1.0 (#12): automático, clareza, redução de ruído, preto e branco, olhos vermelhos.

## 8. Exportação

`exportar.py` + `ui/exportar_dialog.py`:

- **Conferência antes**: lista impressões com resolução baixa, originais que sumiram ou mudaram (bytes/mtime) e
  fotos selecionadas sem impressão; a pessoa pode voltar ou seguir.
- **Destino**: pasta escolhida (lembra a última; padrão: Imagens) + a **pasta principal com o nome que a pessoa
  escreve** no diálogo ("Nome da pasta", padrão `Revelação AAAA-MM-DD`; `planejar(..., nome=...)`,
  `nome_principal()`: limpo para o Windows; se já existir, ` (2)`...). Dentro, uma subpasta **por tamanho** com o
  nome do laboratório (`10x15`, `15x21`, `A4`...).
- **Acabamento por tamanho** (`Acabamento(borda, papel)`, `planejar(..., acabamentos={"10x15": ...})`): no diálogo,
  uma linha por tamanho exportado com **Borda** (não informar, sem borda, borda fina, borda grossa: `BORDAS`) e
  **Papel** (não informar, fosco, brilho, semibrilho: `PAPEIS`), lembrados por tamanho em
  `exportar/acabamento/<tamanho>` (`"borda|papel"`). É **só um aviso para o laboratório**: vai no fim do nome da
  subpasta (`com_acabamento()`: `10x15 - borda fina - fosco`; organizado por pasta, `Família - fosco`, pelo tamanho
  da pasta) e na seção "Acabamento (para o laboratório)" do `pedido.txt`; a foto sai sem borda. Não informado, o
  nome fica só o tamanho.
- **Organizar por** (#32; `planejar(..., organizar="tamanho"|"pasta")`, `ORGANIZAR_TAMANHO`/`ORGANIZAR_PASTA`,
  lembrado em `exportar/organizar`; a opção só aparece no diálogo quando o trabalho tem pastas): **por tamanho** (o
  padrão) como acima; **por pasta**, cada pasta de tamanho vira uma subpasta com o nome dela (`nome_subpasta()`: tira
  os caracteres proibidos do Windows, trata `CON`, `COM1` e afins, corta em 80 caracteres) e as impressões avulsas
  continuam em subpastas por tamanho. As pastas escolhem o nome primeiro; nomes repetidos sem diferenciar maiúsculas
  ganham ` (2)`. Dentro de cada subpasta vale o mesmo esquema de cópias. `Item` ganha `grupo` e `pasta`; `Plano`
  ganha `organizar`. O custo não muda (continua por tamanho).
- **Cópias** (opção; no diálogo o padrão é *repetir*, e a última escolha é lembrada em `exportar/copias`;
  `planejar()` sem o argumento usa *pastas*):
  - `pastas`: `10x15/1 cópia/…`, `10x15/2 cópias/…` (sem subpasta se todas forem 1 cópia);
  - `nome`: `IMG_1234 (2 cópias).jpg`;
  - `repetir`: o arquivo gravado N vezes (`IMG_1234.jpg`, `IMG_1234 - 2.jpg`), para laboratórios que contam
    arquivos.
- **Nome**: o nome original sem extensão (caracteres proibidos do Windows viram `_`) + `.jpg`. Colisão dentro do
  plano (mesma foto duas vezes no mesmo tamanho, fotos de pastas diferentes com o mesmo nome; sem diferenciar
  maiúsculas) ganha ` - 2`, ` - 3`...; a pasta `Revelação AAAA-MM-DD` nunca é uma que já existe. `planejar()` não
  toca no disco e guarda uma **cópia** do trabalho, então a exportação roda em outra thread com a interface viva.
- **JPEG**: `uint8`, qualidade 95, subamostragem 4:4:4, **baseline** (algumas máquinas de laboratório recusam
  progressivo), `dpi=(dpi, dpi)`, perfil sRGB embutido, EXIF mínimo: só a data original (sem GPS, sem orientação,
  sem miniatura). Gravação em `*.tmp` na mesma pasta + `os.replace`.
- **Resumo** `pedido.txt` na raiz da exportação: data, dpi, por tamanho o número de fotos e de cópias, o valor por
  cópia e o subtotal (quando houver preço; seção 13), o total estimado e a lista de arquivos com cópias. Organizado
  por pasta, ganha a seção "Pastas" (subpasta, tamanho, fotos e cópias), porque o laboratório não deduz o tamanho
  por um nome como "Família". É o que a
  pessoa mostra ou envia ao laboratório.
- **Execução**: fila num `QThreadPool` (até `min(4, núcleos − 1)` em paralelo), cada tarefa
  `receita(original) → JPEG`; progresso por arquivo; erro de um item não derruba os outros (fica em
  `Resultado.erros` e no `pedido.txt`); enquanto roda, a detecção de rostos fica pausada (seção 5.2); cancelar
  termina o arquivo atual, apaga os `*.tmp` e informa o que ficou
  pronto. No fim: "Abrir a pasta" (`system.reveal`). `exportar.py` é puro (sem Qt); o diálogo é testável sem modal
  (`definir_destino`, `iniciar`, `aguardar`, `cancelar`).
- Testes: px e dpi exatos, perfil sRGB presente, sem orientação/GPS, nomes e pastas para cada modo de cópias,
  nada sobrescrito, original intacto (SHA-256 antes/depois), cancelamento sem `*.tmp` sobrando.

## 9. Formato `.revelador`

JSON UTF-8, `projeto.FORMATO = 1`. Campos opcionais só aparecem quando usados (o que falta vale o padrão). Ao
abrir, `sanitize()` valida tudo: valores fora da faixa são limitados e tamanho desconhecido vira o padrão, com
aviso. Formato maior que `FORMATO` é recusado com aviso ("feito por uma versão mais nova").

```json
{
  "app": "Revelador",
  "formato": 1,
  "versao_app": "0.1.0",
  "padrao": {"tamanho": "10x15", "dpi": 300, "margem_corte_mm": 2.0},
  "pastas": [{"id": "p3f9a0c1b2d4", "nome": "Família", "cor": "azul", "tamanho": "15x21", "copias": 2}],
  "fotos": [
    {
      "id": "f1",
      "caminho": "Fotos/IMG_1234.HEIC",
      "caminho_absoluto": "C:\\Users\\fulano\\Pictures\\Fotos\\IMG_1234.HEIC",
      "bytes": 2481234,
      "mtime": 1767225600.0,
      "selecionada": true,
      "ajustes": {"exposicao": 12, "sombras": 30},
      "rostos": [{"x": 0.41, "y": 0.22, "w": 0.08, "h": 0.11,
                  "olhos": [[0.43, 0.26], [0.47, 0.26]], "confianca": 0.93}],
      "impressoes": [
        {"tamanho": "10x15", "copias": 2,
         "recorte": {"cx": 0.45, "cy": 0.38, "zoom": 1.0, "angulo": 0.0, "giro": 0, "origem": "auto"}},
        {"tamanho": "20x30", "orientacao": "paisagem", "modo": "caber"},
        {"tamanho": "15x21", "copias": 2, "pasta": "p3f9a0c1b2d4"}
      ]
    }
  ]
}
```

- `caminho` relativo à pasta do `.revelador` (com `/`) quando a foto está no mesmo disco; em outro disco vale o
  caminho absoluto; `caminho_absoluto` fica como reserva. Foto não encontrada: o app oferece "Procurar…" e
  reaproveita a pasta para as outras. Foto sem caminho é ignorada, com aviso.
- O tamanho `"personalizado"` é sempre aceito, mesmo com a lista de tamanhos válidos passada a `abrir()`.
- **Pastas** (#32, ainda no formato 1): `pastas` (antes de `fotos`) só é gravado quando há pastas; cada uma com `id`,
  `nome`, `cor`, `tamanho` e, quando usados, `copias`, `papel_mm` e `preco_centavos`. A impressão ganha `pasta` só
  quando não é avulsa. Na leitura, com aviso: tamanho desconhecido vira o padrão (personalizado sem medida também);
  cor vazia ou que não é texto vira `COR_PASTA_PADRAO` (`"azul"`), e uma chave desconhecida é mantida (a interface
  mostra a primeira cor); `id` ausente ou repetido ganha um novo (as impressões do repetido ficam com a primeira
  pasta); impressão com uma pasta que não existe, ou a segunda da mesma pasta na mesma foto, vira avulsa; o tamanho de
  uma impressão de pasta é sempre o da pasta. Arquivo antigo sem pastas abre igual; `tests/data/exemplo_pastas.revelador`
  é o exemplo do formato com pastas.
- Gravação segura por `projeto.gravar_texto_seguro()` (`.tmp` na mesma pasta + `os.replace`).
- **Salvamento automático** (#34, `ui/autosalvar.py`, `AutoSalvar`, na janela como `autosalvar`): a cada intervalo
  (padrão **1 min**), se o trabalho tem alterações, ele é gravado sozinho, sem perguntar: o texto é montado na thread
  principal (rápido) e gravado em segundo plano; a interface nunca trava. Trabalho com arquivo → no próprio
  `.revelador`. Trabalho novo → nome automático "Revelação AAAA-MM-DD HH-MM" (ou o nome da primeira pasta importada:
  a janela avisa o `AutoSalvar` antes de importar), em `Imagens\Revelador\Trabalhos\` (trocável nas
  Configurações; com `REVELADOR_SETTINGS_DIR`, `<essa pasta>/Trabalhos`, para os testes nunca gravarem nas Imagens de
  verdade), nome livre sem sobrescrever, e entra nos recentes. Trabalho novo vazio (sem fotos) nunca vira arquivo.
  O app sabe quais arquivos ele mesmo criou pela preferência `autosalvar/automaticos` (lista JSON), sem mudar o
  formato: "Salvar" num arquivo automático pergunta onde salvar, como um trabalho sem nome (escolher o mesmo caminho o
  torna da pessoa, sem apagar nada); "Salvar como…" grava no lugar novo e **apaga o arquivo automático antigo** (só
  ele). Indicador discreto na barra de status ("Salvo às 14:32" / "Salvando…"); falha → faixa de aviso não modal, o
  trabalho continua modificado e nada se perde. Com o automático ligado, fechar o app e trocar de trabalho (Novo,
  Abrir, recuperar) **salvam sem perguntar**; se a gravação falhar, a pergunta volta. Desligado, vale o
  `perguntar_salvar` de sempre. Um salvamento manual espera o automático em andamento terminar (`ProjetoUi.salvo`
  avisa as gravações manuais). Preferências: `autosalvar/ligado` (padrão ligado), `autosalvar/intervalo_min` (1 a 60,
  padrão 1) e `autosalvar/pasta` (vazio = a pasta padrão).
- **Recuperação** (rede de segurança, mantida): autossalvamento a cada 2 min em
  `%LOCALAPPDATA%\Revelador\recuperacao\<nome>.revelador` (ou `sem-nome.revelador`), com caminhos absolutos; na
  abertura depois de uma falha, oferece recuperar. Um salvamento automático bem-sucedido apaga as cópias de
  recuperação, então na prática ela só guarda o que mudou desde o último salvamento — e continua valendo por inteiro
  quando o automático está desligado ou falhando. Por isso não foi simplificada.
- O `.msi` associa `.revelador` ao app (recurso opcional `AssociacaoRevelador` no `.wxs`, ProgId `Revelador.Trabalho`,
  só em `HKCU\Software\Classes`).
- **Interface** (`ui/projeto_ui.py`, `ProjetoUi`, na janela como `projeto_ui`): liga `acao_novo`, `acao_abrir`,
  `acao_salvar`, `acao_salvar_como` e `menu_recentes` (até 10 caminhos na preferência `projeto/recentes`). O título da
  janela mostra o nome do trabalho e `*` quando há alterações. Trocar de trabalho ou fechar com alterações pergunta
  Salvar / Descartar / Cancelar (`perguntar_salvar`). Avisos, a oferta de **recuperação** depois de uma falha e o
  **religar fotos** ("Procurar…": escolhe uma pasta, procura pelo nome nas subpastas e reaproveita o achado para as
  outras fotos que faltam; teto de 300 mil arquivos olhados) aparecem em **faixas não modais** (`PilhaFaixas`) logo
  abaixo da barra superior; só as escolhas de arquivo/pasta e a pergunta de salvar abrem diálogo (os testes as
  substituem). "Procurar…" também está no menu de contexto da grade quando alguma foto escolhida falta no disco.
  Foto que falta fica na grade com erro, sem derrubar o resto. **Arrastar um `.revelador`** para a janela abre o
  primeiro solto por `projeto_ui.abrir` (adiado por um `QTimer`, para a pergunta de salvar não travar o Explorer); as
  fotos e pastas soltas junto entram depois no trabalho aberto (se a pessoa cancelar, nada entra). **Linha de comando**:
  `app.separar_argumentos` manda o primeiro `.revelador` para `projeto_ui.abrir` e o resto (fotos e pastas) para a
  importação.

## 10. Interface

O visual é próprio: **só tema escuro**, cinzas neutros (R = G = B, para não enganar a percepção de cor da foto) e o
laranja das marcas de corte do logo como única cor de destaque (botão principal, seleção, controle ligado, foco). O
app **não** segue o claro/escuro do Windows. Não há barra de menus nem barra de ferramentas do Qt.

```
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ Revelador [Importar ▾] [Projeto ▾]  Mostrar [Todas|Selecionadas]  Tamanho [10x15 ▾]  (R$ 34,40) [Exportar]  ⚙ │
├─ faixas não modais (avisos, recuperação, "Procurar…") ───────────────────────────────────────┤
├────────────────┬───────────────────────────────────────────────┬──────────────────────────┤
│ ▾ PASTAS  + Nova│  Editor: a foto com a moldura do papel          │ Painel em cartões        │
│ ● Família 10x15 │  · fora do papel escurecido                     │ ▸ Impressões             │
│ ☑ marca         │  · margem de corte tracejada                    │   10x15 ×2  (retrato) ✎  │
│ 10x15 ×2        │  · aviso de resolução                           │   + Adicionar tamanho    │
│ ⚠ resolução     │  rodapé: ícones · Automático · Moldura|Resultado │ ▸ Luz  ▸ Cor  ▸ Detalhe │
│                 │          endireitar ──●──                       │ [Comparar][Copiar][Colar]│
├────────────────┴───────────────────────────────────────────────┴──────────────────────────┤
│ 37 fotos · 12 selecionadas · 10x15: 15 cópias · 20x30: 1 cópia                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Barra superior** (`MainWindow`, `BarraAdaptavel`: some rótulos e botões opcionais quando a janela estreita):
  logo e nome; **Importar ▾** (arquivos, pasta); **Projeto ▾** (Novo, Abrir, Abrir recente, Salvar, Salvar como,
  Desfazer, Refazer); **Mostrar** (Todas | Selecionadas, `filtro_mostrar`); **tamanho padrão**
  (`SeletorTamanhoPadrao`); a **pílula de custo** (`Pilula`: total estimado do pedido); **Exportar para revelação**
  (botão `Primary`); e a **engrenagem** (Preços do laboratório…, Resumo do pedido, Configurações…, Tela de
  boas-vindas, Verificar atualizações…, Sobre).
- **Grade** (`ui/grade.py`, `QListView` em modo ícone + modelo e delegate próprios, miniaturas sob demanda do
  cache em disco): cartão por foto com marca de seleção (clique na marca ou Espaço), etiqueta de tamanho(s) e
  cópias, aviso de resolução baixa e de erro; Delete tira do trabalho (nunca do disco). Seleção múltipla
  (`fotos_escolhidas`) vale para Espaço, Delete e para colar ajustes. Clicar no chip "10x15 ×2" soma uma cópia
  àquela impressão e Shift+clique tira uma (limites 1 e 999); a foto clicada vira a atual e a impressão, a do editor.
  - **Tamanho das miniaturas** (#31): controle "Miniaturas" no rodapé da grade e Ctrl + roda do mouse sobre ela, de
    80 a 320 px em passos de 10 (`MINIATURA_MINIMA`, `MINIATURA_MAXIMA`, `PASSO_MINIATURA`), padrão 150
    (`MINIATURA_PADRAO`), lembrado em `grade/miniatura`. Célula, marca, chips e nome acompanham o tamanho; abaixo de
    120 px (`LADO_COMPACTO`) o nome some e os chips mostram só a contagem de cópias. Mudar o tamanho não relê as
    fotos: a miniatura vem sempre do cache de 320 px (`miniaturas.py`).
  - **Duas colunas no mínimo**: a largura mínima da área da grade é a de duas colunas no tamanho escolhido
    (`grade.largura_duas_colunas`), recalculada quando o tamanho muda (`Grade.tamanho_mudou`); ao abrir, uma largura
    de divisória salva menor que isso (como os 260 px da primeira versão) é corrigida e o editor cede o que falta
    (`MainWindow._corrigir_largura_grade`).
  - **Menu de contexto** (#5, #9; `Grade.menu_contexto(fotos) -> QMenu`, montado sem `exec()`, itens identificados
    pelo `objectName`): Marcar / Desmarcar para revelação, **Tamanho ▸** (os tamanhos da tabela), **Cópias ▸** (1, 2,
    3, 5, 10, uma a mais, uma a menos), **Procurar…** (só quando alguma escolhida falta no disco: `procurar_pedido` →
    `projeto_ui.procurar_faltando`) e Remover do trabalho. Vale para todas as fotos escolhidas (Ctrl/Shift) e cada
    ação é **um passo só** do desfazer (`estado.lote`), como Espaço em várias fotos. Tamanho: marca a foto se preciso
    e troca a **primeira impressão avulsa** (recorte automático refeito, manual reencaixado), sem mexer nas outras
    avulsas nem nas de pastas; se alguma avulsa já está nesse tamanho, nada muda; foto só com impressões de pastas
    ganha uma avulsa. Cópias: todas as impressões da foto, limitadas a 1..999. **Adicionar à pasta ▸** (as pastas
    + "Nova pasta…"; a pasta em que todas as escolhidas já estão aparece desligada, com um anel na bolinha) e **Tirar
    da pasta ▸** (quando alguma escolhida está numa pasta) vêm logo depois de "Cópias ▸".
  - **Pastas de tamanho** (#32, `ui/pastas.py`, `SecaoPastas`, ligada em `_ligar_pastas()`): seção no topo da grade,
    acima da lista, que aparece e some com ela. Cabeçalho "PASTAS" com "+ Nova pasta", recolhível (lembrado em
    `grade/pastas_recolhidas`; recolhida, mostra o nome da pasta filtrada); "Todas" e uma linha por pasta com a
    bolinha da cor, o nome, o tamanho, o número de fotos e o botão "⋯". Sem pastas, só o cabeçalho; a partir de 5
    pastas a lista rola (`MAX_LINHAS`). Com a grade estreita o nome é cortado com "…" e o tamanho some antes da
    contagem; a seção não aumenta a largura mínima da grade. **Nova pasta** (`PastaDialog`, testável sem `exec()`):
    nome, tamanho (o padrão já escolhido, inclusive personalizado) e cor (`SeletorCor`, a paleta `CORES_PASTA`, já na
    próxima cor livre). **Menu da pasta** (clique direito ou "⋯"): renomear, cor, tamanho (inclusive personalizado),
    cópias padrão, mover para cima/baixo e apagar (com confirmação substituível em teste). **Clicar numa pasta filtra
    a grade** (`Grade.definir_pasta`) em conjunto com "Mostrar": a grade mostra as fotos que passam nos dois (pasta
    "Natal" + Selecionadas = as fotos marcadas da "Natal"); clicar de novo na pasta, ou em "Todas", tira o filtro de
    pasta sem mexer na barra superior; se a pasta filtrada some (apagada ou desfeita), volta a "Todas".
    **Arrastar fotos da grade para uma pasta** (várias de uma vez) usa o mime próprio `application/x-revelador-fotos`
    (`MIME_FOTOS`, só os ids, sem URLs: soltar no Explorer nunca copia nem move o original). Na miniatura, o **chip do
    tamanho ganha a cor da pasta** (`layout_chips(..., pastas=)` devolve `Chip`, uma tupla de 4 com `.cor`; no modo
    compacto, a cor da primeira impressão de pasta). Nomes de objeto novos no tema: `SecaoPastas` e `SecaoTitulo`;
    ícone `opcoes` e `icones.bolinha(cor, anel=)`.
  - A grade publica no `Estado` a ordem visível (`definir_visiveis`, com o filtro aplicado: navegação ←/→ do
    editor) e, com espera de 150 ms ao rolar ou redimensionar, as fotos que aparecem no viewport (`definir_na_tela`:
    prioridade dos rostos, seção 5.2).
- **Editor** (`ui/editor.py`, widget próprio): seletor **Moldura | Resultado**. Moldura: a foto inteira com a
  moldura do papel na proporção exata, fora do papel escurecido, margem de corte tracejada, opção de mostrar os
  rostos; arrastar move o recorte, a roda dá zoom, tudo passa por `enquadramento.reencaixar`. Resultado: a prévia
  pela receita. Rodapé (`Rodape`) com a informação do tamanho e da resolução, ícones de girar 90°, **Girar papel**
  (retrato ↔ paisagem, `O`), zoom −/+, rostos, "Enquadrar pelos rostos" (numa foto ainda sem detecção, pede os
  rostos na hora e refaz o recorte quando chegam) e o slider de endireitar.
  - **Alças nos cantos** (#6): um "L" em cada canto do papel, laranja sob o mouse. Arrastar uma alça muda só o zoom
    com o **canto oposto parado** (o tamanho acompanha o mouse ao longo da diagonal do papel, zoom de 1 a
    `ZOOM_MAXIMO`), com a proporção exata e o recorte sempre dentro da imagem (empurrado para dentro quando o canto
    oposto não pode ficar parado); o cursor de redimensionar acompanha o endireitar; o recorte vira `"manual"`.
    Durante o arrasto só a moldura é redesenhada. Sem alças no modo *caber* e no Resultado. Gesto chamável direto:
    `Editor.puxar_canto(canto, ponto)`.
  - **←/→ entre as fotos** (#6): com o foco no visor ou no rodapé do editor (o editor aceita foco por clique), ← e →
    vão para a foto anterior/seguinte entre as visíveis na grade (respeita o filtro, para nas pontas;
    `estado.vizinha`), Home/End para a primeira/última (`Editor.navegar(passo)`, `Editor.ir_para_ponta(ultima)`). O
    slider de endireitar continua usando as setas e a grade continua navegando quando o foco está nela. Impressão em modo *caber* mostra sempre o resultado.
- **Painel lateral**: coluna rolável de **cartões** (`Card`): **Impressões** (`ui/painel_impressoes.py`: tamanhos
  com cópias, orientação, modo preencher/caber, "+ Adicionar tamanho", remover, tamanho personalizado), **Luz**,
  **Cor** e **Detalhe** (`ui/painel_ajustes.py`, gerados de `ajustes.PARAMS`/`GRUPOS`; duplo clique no controle volta
  ao padrão, o botão do cartão restaura o grupo) e botões de comparar, copiar, colar e restaurar todos.
  - **Impressão de pasta** (#32): mostra o nome e a cor da pasta; o combo de tamanho fica desligado, com a dica de
    mudar pelo menu da pasta (vale para todas as fotos dela); remover essa impressão tira a foto da pasta
    (`tirar_da_pasta`), mesmo sendo a última — e aí a foto fica desmarcada.
  - **Orientação explícita** (#33): no lugar de um combo com "Automática", um `Segmented` **Retrato | Paisagem**. Com
    `orientacao = "auto"`, vem marcada a opção resolvida pela forma da foto (`tamanhos.orientacao_efetiva` sobre a
    imagem já girada), com o indicador discreto "auto" (dica: "escolhida pela forma da foto"); clicar numa opção fixa
    a orientação e **Voltar ao automático** devolve `"auto"`. O modelo continua com `"auto"`, `"retrato"` ou
    `"paisagem"`: só a apresentação mudou. **Girar papel** (no cartão, no rodapé do editor e pelo atalho `O`) troca
    retrato ↔ paisagem fixando a escolha; o recorte automático é refeito e o manual é reencaixado na nova proporção,
    mantendo a `origem`.
  - **Cópias rápidas** (#33): botões − e + bem visíveis ao lado da quantidade ("× n"), os atalhos `+` (ou `=`) e `−`
    na impressão atual e o clique no chip da grade; limites 1 e 999 (`LIMITE_COPIAS`). Custo, chip e resumo
    atualizam na hora (`estado.alterar(foto, pedido=True)`).
- **Atalhos** (os que existem hoje): Ctrl+I importar fotos · Ctrl+Shift+I importar pasta · Ctrl+E exportar · Ctrl+N
  novo · Ctrl+O abrir · Ctrl+S salvar · Ctrl+Shift+S salvar como · Ctrl+Q sair · Espaço marca/desmarca ·
  Delete remove da grade · Ctrl+Z desfazer · Ctrl+Y / Ctrl+Shift+Z refazer · ← / → foto anterior / seguinte e
  Home / End primeira / última (foco no editor) · R / Shift+R gira 90° (horário / anti-horário) · O gira o papel
  (retrato ↔ paisagem) ·
  A recorte automático (pelos rostos) · `+` / `−` uma cópia a mais / a menos na impressão atual · Ctrl++ / Ctrl+−
  zoom · Ctrl + roda do mouse sobre a grade muda o tamanho das miniaturas · **segurar `\`** mostra o antes/depois ·
  Ctrl+Shift+C / Ctrl+Shift+V copiar/colar ajustes.
- **Arrastar e soltar** fotos e pastas na janela importa (recursivo, só formatos suportados); um `.revelador` solto
  abre o trabalho (seção 9).
- **Importar pasta** (#32, `MainWindow.escolher_pasta`): depois de escolher a pasta do disco, um passo curto
  (`PassoImportarPasta`, testável sem `exec()`): "Criar pasta de tamanho" já marcado, nome = o da pasta do disco
  (editável), tamanho = o padrão, cor = a próxima da paleta. Marcado, todas as fotos daquela pasta do disco entram
  marcadas para revelação na pasta de tamanho (inclusive as que já estavam no trabalho), num passo só do desfazer
  ("Desfazer importação da pasta “X”"; a importação em si fica fora do desfazer); sem nenhuma foto, nenhuma pasta é
  criada. Desmarcado, só importa; cancelar não importa nada. Vale para "Importar pasta…" da barra e da tela de
  boas-vindas; uma pasta arrastada do Explorer continua só importando.
- **Desfazer/refazer** (#5; modelo na seção 2): `acao_desfazer`/`acao_refazer` ligadas em `_ligar_desfazer()`,
  habilitadas por `canUndo`/`canRedo`, com o texto "Desfazer {o quê}" deduzido da mudança ("Desfazer tamanho 15x21",
  "Desfazer cópias em 3 fotos"). Gestos contínuos viram um passo só: `alterar(foto, *, pedido=False, juntar=None)` —
  chamadas seguidas com a mesma chave (`recorte:<i>`, `endireitar:<i>`, `ajuste:<chave>`), na mesma foto e sem outro
  passo no meio, se juntam até `fim_gesto()` (soltar o mouse ou o slider), cerca de 1 s parado (`JUNTAR_MS`, para a
  roda do mouse) ou um desfazer/refazer; `comecar_gesto()` segura a junção durante um arrasto (pausar no meio não
  divide o passo). O giro de 90° é sempre um passo próprio. O filtro que marca começo e fim dos gestos do editor
  (visor e slider de endireitar) é instalado pela janela (`desfazer.ligar_gestos(estado, *widgets)`), sem mexer nos
  eventos do editor. `lote(texto)` junta tudo o que acontece dentro dele num passo (aninha, vale o texto de fora,
  lote vazio não empilha).
- **Configurações** (#34, `ui/configuracoes.py`, `ConfiguracoesDialog`, engrenagem → Configurações…, ligada em
  `_ligar_autosalvar()`): diálogo em seções (subclasses de `Secao`, identificadas por `id_secao`), por enquanto com o
  salvamento automático (ligado, intervalo em minutos, pasta dos trabalhos automáticos); ao aplicar, emite `aplicado`
  e o `AutoSalvar` relê as preferências. Testável sem `exec()`.
- **Barra de status**: à esquerda o resumo do pedido e as mensagens de progresso (importação, "Rostos: 12 de 80");
  à direita, o indicador permanente do salvamento automático ("Salvo às 14:32" / "Salvando…").
- **Tela de boas-vindas** (#35, `ui/boas_vindas.py`, `BoasVindas`, na janela como `boas_vindas`, ligada em
  `_ligar_boas_vindas()`): uma página que toma o lugar das três áreas (abaixo da barra superior e das faixas), com a
  mesma largura mínima delas, e funciona em janela estreita. Aparece ao abrir o app **sem arquivos na linha de
  comando** (`app.main` chama `janela.boas_vindas.ao_abrir()` depois de tratar os argumentos; testes e capturas que
  criam a `MainWindow` direto não a veem) se `boas_vindas/mostrar_ao_abrir` estiver ligada (padrão; interruptor na
  própria tela), e também pela engrenagem (`acao_boas_vindas`). Sai sozinha quando a lista de fotos muda (trabalho
  novo, aberto ou recuperado, importação), pelo "Fechar" e pelo Esc. Tem: ações grandes **Novo trabalho**,
  **Importar fotos**, **Importar pasta** e **Abrir trabalho…** (disparam as ações do contrato); **Trabalhos
  recentes** (`projeto_ui.recentes()`, salvos à mão ou automaticamente), cada um com nome e data, número de fotos e de
  selecionadas, tamanhos e 3–4 miniaturas do cache (lidos em segundo plano), abertos com um clique, removíveis da lista
  (`projeto_ui.esquecer_recente`), e os que não existem mais somem; o trabalho **recuperável** em destaque, com
  Recuperar e Descartar (enquanto a tela está aberta, a faixa de recuperação vira esse cartão; ao fechar, a faixa
  volta se a cópia ainda existir); **Novidades desta versão** (`revelador/novidades/release_v{versão}.md`, o mesmo
  arquivo das notas da release); **Atualizações** ("Versão X disponível" com o botão que abre o diálogo da seção 11,
  ou "Você está na versão mais recente"); e a dica do fluxo Importar → Marcar e enquadrar → Exportar. As novidades
  abrem sozinhas (diálogo) **uma vez depois de cada atualização**: `boas_vindas/versao_vista` guarda a última versão
  vista; na primeira execução só é gravada.
- **Preferências** (`ui/prefs.settings()`): `QSettings` no registro (`HKCU\Software\Revelador\Revelador`) ou, com
  `REVELADOR_SETTINGS_DIR`, num `.ini`. Guarda geometria e divisórias da janela, últimas pastas, tamanho padrão, dpi,
  modo de cópias, a organização da exportação (`exportar/organizar`), preços, o tamanho das miniaturas
  (`grade/miniatura`), a seção de pastas recolhida (`grade/pastas_recolhidas`), `projeto/recentes`, o salvamento automático (`autosalvar/ligado`, `autosalvar/intervalo_min`,
  `autosalvar/pasta`, `autosalvar/automaticos`; seção 9), a tela de boas-vindas (`boas_vindas/mostrar_ao_abrir`,
  `boas_vindas/versao_vista`) e as chaves `atualizacao/*` (seção 11).
- **Erros**: `crashlog.py` instala `sys.excepthook` e `threading.excepthook`, grava em
  `%LOCALAPPDATA%\Revelador\logs\erro-<data>.txt` (até 20 arquivos de 256 KB cada) e mostra uma mensagem curta
  com "Abrir registro".
- **Tema e componentes**: `ui/tema.py` tem **todas** as cores, medidas e a folha de estilo (nomes de objeto
  `TopBar`, `Panel`, `Card`, `Primary`, `Flat`, `Danger`, `Seg`, `Muted`, `Faint`, `PanelTitle`, `Kicker`, `Canvas`,
  `Rodape`, `Pilula`...); nenhum widget escreve hexadecimal nem `setStyleSheet` próprio (só troca o `objectName`).
  `ui/icones.py` desenha os ícones com `QPainter` (sem arquivos); `ui/componentes.py` tem `Card`, `Slider`,
  `Segmented`, `ToggleSwitch`, `Pilula` e `BarraAdaptavel`. `tools/captura_tela.py` gera PNGs da janela, dos
  diálogos, dos menus e um catálogo dos componentes para a revisão visual (plataforma `windows`; `offscreen` não
  tem fontes).
- **`MainWindow`** (`ui/main_window.py`) e o **contrato das ações**: a janela cria `acao_importar`,
  `acao_importar_pasta`, `acao_exportar`, `acao_novo`, `acao_abrir`, `acao_salvar`, `acao_salvar_como`,
  `menu_recentes`, `acao_desfazer`, `acao_refazer`, `acao_configuracoes`, `acao_boas_vindas`,
  `acao_verificar_atualizacoes`, `acao_precos`, `acao_resumo`, `acao_sobre` e `acao_sair`, com
  atalho valendo na janela inteira; a barra superior só as posiciona. As que ainda não têm dono ficam desligadas;
  **cada parte conecta e liga as suas** num `_ligar_<parte>()` chamado no fim do `__init__`. Ninguém cria menu ou
  botão de barra por conta própria. `arquivos_iniciais` guarda os caminhos da linha de comando.
- **Estado compartilhado** (`ui/estado.py`, `janela.estado`): os widgets **não se conhecem**; leem e mudam o
  modelo por ele e reagem aos sinais. Só a thread principal o toca; workers devolvem por sinal.
  - Sinais: `fotos_mudaram()` (lista mudou), `atual_mudou(foto | None)`, `impressao_mudou(indice)` (impressão do
    editor), `foto_mudou(id)` (qualquer mudança numa foto), `pedido_mudou()` (muda orçamento ou exportação),
    `modificado_mudou(bool)`, `comparando_mudou(bool)`, `pastas_mudaram()` (pastas de tamanho), `rostos_pedidos(id)`
    (alguém quer os rostos desta foto já) e `exportando_mudou(bool)`.
  - Atributos: `trabalho`, `atual`, `indice_impressao`, `info` (`InfoFoto` por id), `miniaturas` (JPEG do cache por
    id), `erros` (mensagem amigável das fotos que não abriram, por id), `comparando` (antes/depois; não vai para o
    arquivo), `modificado`, `impressao_atual`, `visiveis` (ids visíveis na grade, na ordem dela), `na_tela` (ids no
    viewport da grade), `exportando` e `pilha` (o `QUndoStack`).
  - Métodos: `por_id`, `definir_trabalho`, `adicionar`, `remover`, `definir_atual`, `definir_impressao`,
    `definir_info`, `definir_miniatura`, `definir_erro`, `definir_rostos`, `definir_comparando`, `selecionar` (a
    primeira seleção cria uma impressão no tamanho padrão), `refazer_recortes_auto` (usa `recorte_sugerido` nas
    impressões não manuais), `alterar(foto, *, pedido=False, juntar=None)`, `marcar_modificado`, `definir_visiveis`,
    `vizinha(passo)`, `definir_na_tela`, `pedir_rostos(foto)`, `definir_exportando`; desfazer: `lote(texto)`,
    `desfazer`, `refazer`, `comecar_gesto`, `fim_gesto`, `absorver(foto)`; pastas de tamanho: `pasta_por_id`,
    `impressao_da_pasta`, `fotos_da_pasta`, `pastas_da_foto`, `criar_pasta`, `alterar_pasta`, `mover_pasta`,
    `apagar_pasta`, `adicionar_a_pasta`, `tirar_da_pasta` e `alterar_pastas`. Mexeu no modelo →
    `estado.alterar(foto, pedido=...)` (várias fotos: dentro de um `lote`); mudança que vem do sistema e não deve
    virar passo do desfazer → `absorver(foto)`.
- **Pendências conhecidas**: miniatura da grade com os ajustes, os títulos dos grupos (Comuns, Ampliações,
  Quadrados) no submenu "Tamanho ▸" (o estilo do Qt só desenha separadores) e o aviso inofensivo do OpenCV no
  stderr.

## 11. Atualização automática

`updater.py` é o mesmo desenho do PeliculaConverter (`pelicula/updater.py`), só para o Windows por enquanto:

- `REPO = "edvitor13/revelador"`; consulta `releases/latest` (pre-releases ficam de fora), compara
  `parse_version(tag)` com `__version__`. `is_newer()` ignora tags com `-`. `can_auto_install()` é falso fora do
  Windows.
- `install_info()` lê `revelador-install.json` ao lado do executável (`{"kind": "msi"|"zip", "version"}`); sem
  marcador num executável empacotado → `zip`; rodando do código-fonte → `source` (só mostra o link).
- `PATTERNS = {"msi": r"-windows-x64\.msi$", "zip": r"-windows-x64\.zip$"}` escolhe o pacote da release.
- `download()` exige o `SHA256SUMS.txt` da release e confere o SHA-256 antes de qualquer coisa.
- `install()` escreve um `.ps1` que espera o app fechar, roda `msiexec /i … /passive /norestart` (msi) ou
  `robocopy /MIR` da pasta extraída (zip: recusa entrada com caminho absoluto, unidade/UNC, barra inicial ou `..`,
  validado **antes** de extrair), e reabre o app por
  `ProcessStartInfo` com `UseShellExecute = false`. O PowerShell sobe com `CREATE_NO_WINDOW` (nunca
  `DETACHED_PROCESS`, que faz o PowerShell sair sem rodar o script quando o pai não tem console). Registro em
  `atualizar.log` e `instalar.log` na pasta do download.
- Interface (`ui/atualizacao.py`): `Verificador.verificar_ao_abrir()` roda **2 s depois** de a janela aparecer
  (`ATRASO_ATUALIZACAO_MS`), em segundo plano, no máximo **uma vez por dia** (`atualizacao/ultima_verificacao`) e só
  com `atualizacao/automatica` ligada (padrão); sem internet é silenciosa. `atualizacao/pulada` guarda a tag que a
  pessoa mandou pular. O diálogo (não modal) mostra as notas da versão, "Instalar e reiniciar", "Depois" e "Pular
  esta versão", avisa se há alterações não salvas antes de fechar o app e, sem instalação automática (código-fonte,
  release sem o pacote), mostra só o link. "Verificar atualizações…" (engrenagem) sempre responde, inclusive com
  "já está na versão mais recente". **`REVELADOR_SEM_REDE`** (qualquer valor) desliga a consulta ao abrir: testes e
  capturas de tela a definem.
- Para a tela de boas-vindas (#35), o `Verificador` tem também o sinal `verificado(release, erro)`, o atributo
  `ultimo` (o último resultado), `consultar_silencioso()` (consulta sem caixa nem diálogo, que não conta como a
  verificação do dia), `deve_verificar_ao_abrir()` e `mostrar_dialogo(release)`. Ao abrir o app, a tela espera a
  verificação do dia se ela for rodar; com `REVELADOR_SEM_REDE`, mostra só a versão atual, sem consultar.

## 12. Empacotamento

- **`Revelador.spec`** (PyInstaller, pasta única): `Revelador.exe` sem console, ícone `assets/logo.ico`,
  metadados de versão do Windows (pt-BR) lidos de `revelador/__init__.py`; dados: `assets/` e, se existirem,
  `revelador/data/` e `revelador/novidades/`.
- **`--diagnostico ARQUIVO.json`** (`diagnostico.py`): sem abrir janela, faz uma operação real com cada dependência
  nativa — JPEG com perfil sRGB e 300 dpi (Pillow + LittleCMS), HEIF codificado e decodificado (pillow-heif),
  `cv2.resize` e `cv2.FaceDetectorYN` (OpenCV), `QImage` (Qt), numpy — e grava o resultado. O CI roda no
  executável recém-gerado e no instalado pelo `.msi`: uma DLL esquecida pelo PyInstaller aparece no CI, não na
  casa da pessoa. Quando o modelo YuNet entrar (#4), o diagnóstico passa a carregar o modelo e detectar um rosto
  numa imagem de teste.
- **`.msi`** (WiX 5, `packaging/windows/Revelador.wxs`): por usuário, sem administrador, `MajorUpgrade`,
  `UpgradeCode` fixo, atalho no Menu Iniciar, atalho opcional na Área de Trabalho, `ABRIR_APOS_INSTALAR`.
- **`.zip`** portátil: a mesma pasta com o marcador `zip`.
- Detalhes do CI e da release em [AGENTS.md](../AGENTS.md) (Empacotamento e release).

## 13. Custos da revelação

Previsão do quanto o pedido vai custar, a partir de um **valor base por tamanho** (o preço por cópia que o
laboratório cobra). `precos.py` (puro) + `ui/precos_dialog.py`.

- **Tabela de preços**: `dict[id_do_tamanho, centavos_por_cópia]`, nas preferências (`ui/prefs.settings()`, grupo
  `precos`), porque vale para todos os trabalhos. Editada em "Preços da revelação…" (barra de ferramentas e menu):
  uma linha por tamanho de `tamanhos.TAMANHOS`, campo em reais ("1,50"), vazio = sem preço. Tamanho personalizado
  leva o valor junto, na própria impressão (`preco_centavos`).
- **Dinheiro em centavos inteiros** (regra 16). `ler("1,5") → 150`, `ler("R$ 1.234,56") → 123456`,
  `ler("") → None`; texto inválido é recusado no campo. `formatar(150) → "R$ 1,50"` (milhar com ponto, decimal
  com vírgula, sem depender da localidade do sistema).
- **Cálculo** — `orcamento(trabalho, tabela) → Orcamento` (puro):

  ```python
  @dataclass
  class LinhaOrcamento:
      tamanho: str              # id (ou "personalizado-<w>x<h>")
      nome: str                 # "10x15"
      fotos: int                # fotos diferentes nesse tamanho
      copias: int               # soma das cópias
      unitario: int | None      # centavos por cópia; None = sem preço
      subtotal: int | None      # unitario × copias

  @dataclass
  class Orcamento:
      linhas: list[LinhaOrcamento]   # na ordem da tabela de tamanhos
      total: int                     # soma dos subtotais conhecidos
      completo: bool                 # False se algum tamanho usado está sem preço
  ```

  Só entram fotos **selecionadas** e as impressões delas; cada impressão conta `copias` vezes. Personalizados com
  o mesmo papel e o mesmo preço somam na mesma linha (uma linha por papel + preço), chamada "Personalizado
  {menor}x{maior} mm"; `chave_preco(impressao)` dá o id (`personalizado-<menor>x<maior>`). `ler("0")` é `0`:
  preço zero é diferente de sem preço (`None`).
- **Onde aparece**: barra de status ("Total estimado: R$ 34,40", ou "R$ 30,00 + sem preço" quando parcial),
  janela "Resumo do pedido" (tabela por tamanho: fotos, cópias, valor por cópia, subtotal e total, com atalho para
  editar os preços), diálogo de exportação e `pedido.txt` (seção 8). Atualiza a cada mudança de seleção, tamanho
  ou cópias (o cálculo é instantâneo).
- O valor é sempre chamado de **estimativa**: o laboratório pode cobrar diferente (descontos por quantidade,
  entrega). Faixas de preço por quantidade, taxa de entrega e várias tabelas (uma por laboratório) ficam para
  depois (#12).
- Testes: `ler`/`formatar` (vírgula, milhar, "R$", vazio, inválido); orçamento com vários tamanhos, cópias,
  foto em dois tamanhos, foto não selecionada fora da conta, tamanho sem preço (total parcial), personalizado;
  nenhum `float` no caminho (resultado `int`).

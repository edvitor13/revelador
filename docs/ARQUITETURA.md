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
```

- Os **ajustes são da foto** (valem para todas as impressões dela); o **recorte é da impressão** (cada papel tem
  a sua proporção). Selecionar uma foto cria uma impressão no tamanho padrão com o recorte automático.
- Toda mudança do modelo passa por comandos do `QUndoStack` (desfazer/refazer cobre seleção, impressões,
  recortes e ajustes) e marca o trabalho como modificado.

## 3. Carregar fotos

`imagem.py`:

- **Formatos**: JPEG, PNG, HEIC/HEIF (`pillow_heif.register_heif_opener()`, uma vez), WebP, TIFF. RAW fica para
  depois (#12). Arquivo que não abre vira item com aviso, nunca derruba a importação.
- **Orientação**: `ImageOps.exif_transpose` logo depois de abrir. Daí em diante, "imagem orientada" é a base de
  todas as coordenadas.
- **Cor**: se houver `icc_profile`, `ImageCms.profileToProfile(..., srgb, renderingIntent=RELATIVE_COLORIMETRIC,
  flags=BLACKPOINTCOMPENSATION, outputMode="RGB")`; sem perfil, assume sRGB. CMYK com perfil converte pelo perfil;
  transparência é composta sobre **branco** (cor do papel). Tons de cinza viram RGB.
- **Proxy**: cópia com lado maior ≤ 2048 px para a prévia e a detecção de rostos. Para JPEG use
  `Image.draft("RGB", ...)` (decodificação reduzida pelo DCT), que é várias vezes mais rápida. Cache em memória
  (LRU por bytes, ~512 MB).
- **Miniaturas** (`miniaturas.py`): lado maior 320 px, JPEG q85 em
  `%LOCALAPPDATA%\Revelador\cache\miniaturas\<sha1(caminho|bytes|mtime)>.jpg`; limpeza LRU acima de 500 MB.
  Geradas num `QThreadPool` na ordem em que aparecem na tela.
- **Metadados** úteis: tamanho em px (orientado), data original (EXIF `DateTimeOriginal`) para ordenar, modelo da
  câmera. Nada é escrito de volta no arquivo.
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

- **Personalizado**: largura × altura em cm digitados pela pessoa, gravados na impressão
  (`"tamanho": "personalizado"`, `"papel_mm": [w, h]`), com o valor por cópia opcional junto
  (`"preco_centavos"`, seção 13).
- Os tamanhos variam um pouco entre laboratórios (principalmente o 15x21): a tabela é a referência do app e a
  documentação para o usuário deve dizer para confirmar com o laboratório.
- **dpi**: 300 por padrão (opção 240–400 por trabalho).
- **Resolução efetiva** de uma impressão = px do recorte na foto original ÷ polegadas do papel. ≥ 200 dpi: boa;
  150–199: aceitável (aviso discreto); < 150: baixa (aviso visível na grade, no editor e antes de exportar).
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
- **Giro de 90°** muda `W × H` e a orientação automática; rostos são transformados para o espaço girado na hora
  de usar (ficam gravados no espaço sem giro).

### 5.2 Recorte automático pelos rostos

Detecção (`rostos.py`): **YuNet** (`face_detection_yunet_2023mar.onnx`, do opencv_zoo, licença MIT, ~230 KB) por
`cv2.FaceDetectorYN.create(modelo, "", (w, h), score_threshold=0.6, nms_threshold=0.3, top_k=100)`, sobre o
proxy reduzido a lado maior 1280 px. Devolve `Rosto` normalizado (caixa, olhos, confiança). Descarta rostos com
largura < 1,5% do lado menor da imagem. Roda uma vez por foto, num trabalhador, e o resultado vai para
`Foto.rostos`.

Política (`enquadramento.recorte_automatico(W, H, r, rostos) → Recorte`, pura):

1. **Sem rostos** → centro (`cx = cy = 0,5`, `zoom = 1`, `origem = "centro"`).
2. **Importância** de cada rosto = área × confiança. **Principais** = rostos com importância ≥ 15% da maior
   (tira gente pequena ao fundo).
3. **Região de interesse (ROI)** = união das caixas principais **expandidas**: +60% da altura do rosto para cima
   (cabelo, topo da cabeça), +35% para baixo (queixo, pescoço) e +30% da largura para os lados.
4. Recorte com `zoom = 1` (a impressão usa o máximo da foto) na proporção do papel.
5. **Horizontal**: centraliza no centro da ROI; se a ROI for mais larga que o recorte, centraliza no centróide
   dos rostos ponderado pela importância.
6. **Vertical**: põe a linha dos olhos (média ponderada) a 1/3 do topo do recorte; depois garante o topo da ROI
   dentro do recorte (cabeça nunca cortada) e, se couber, a base da ROI também.
7. Se a ROI não couber nem com `zoom = 1`, descarta o rosto principal menos importante e repete; com um rosto só,
   prioriza a cabeça inteira.
8. Limita à imagem e evita rostos dentro da margem de corte quando houver folga. `origem = "auto"`.

Casos de teste obrigatórios (rostos sintéticos em coordenadas): retrato com um rosto em foto 4:3 deitada para
10x15 em pé; grupo em linha numa foto 16:9 para 10x15 deitado; rosto encostado na borda; selfie com rosto
grande; criança pequena + adulto grande; panorâmica 3:1; foto quadrada; sem rosto.

## 6. Receita única

`receita.renderizar(foto, impressao, destino_px, fonte, trabalho) → np.ndarray` (float32 0..1, H×W×3, sRGB):

1. **Fonte**: `fonte="proxy"` (prévia) ou `"original"` (exportação), já orientada e em sRGB (seção 3).
2. **Giro de 90°**: `np.rot90` (sem perda).
3. **Recorte + endireitar + redimensionar** em uma passagem de qualidade: sem rotação, fatia o retângulo e
   redimensiona com `cv2.resize` (`INTER_AREA` para reduzir, `INTER_LANCZOS4` para ampliar); com rotação, reduz
   antes a ~2× o destino e aplica `cv2.warpAffine` (`INTER_LANCZOS4`, borda replicada) com a matriz
   rotação+escala+translação do `retangulo()`.
4. **Ajustes** (`ajustes.aplicar`) no tamanho de destino.
5. **Modo *caber***: compõe a foto inteira (sem recorte) centralizada sobre papel branco com os px exatos.
6. Saída: para a tela, `uint8` → `QImage`; para a exportação, `uint8` por arredondamento simples (determinístico).

- `destino_px` da exportação = px exatos do papel (seção 4). Da prévia = tamanho do visor × `devicePixelRatio`,
  mantendo a proporção.
- A prévia roda num trabalhador com contador de geração (resultado velho é descartado) e *debounce* de ~60 ms;
  arrastar o recorte mostra a imagem já calculada transformada pelo Qt e recalcula ao soltar.

## 7. Ajustes

`ajustes.PARAMS` (esquema; o painel lateral é gerado dele) e `ajustes.aplicar(rgb, valores)` (pura). Todos de
-100 a 100 com padrão 0 (nitidez: 0 a 100). **Padrão = identidade exata.** Ordem fixa:

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
- Desempenho: uma prévia de ~1600 × 1067 em float32 deve ficar em ~100 ms; ajuste que não couber nisso ganha
  versão reduzida da máscara (ex.: desfoque na metade da resolução e ampliado) — o mesmo código na exportação.
- **Copiar/colar ajustes** entre fotos (Ctrl+C / Ctrl+V; colar em várias selecionadas) e **Redefinir** (por
  ajuste com duplo clique no controle, por grupo e tudo). **Antes/depois**: mesmo recorte sem ajustes.
- Depois da 0.1.0 (#12): automático, clareza, redução de ruído, preto e branco, olhos vermelhos.

## 8. Exportação

`exportar.py` + `ui/exportar_dialog.py`:

- **Conferência antes**: lista impressões com resolução baixa, originais que sumiram ou mudaram (bytes/mtime) e
  fotos selecionadas sem impressão; a pessoa pode voltar ou seguir.
- **Destino**: pasta escolhida (lembra a última; padrão: Imagens) + subpasta `Revelação AAAA-MM-DD` (nome livre:
  ` (2)`...). Uma subpasta **por tamanho** com o nome do laboratório (`10x15`, `15x21`, `A4`...).
- **Cópias** (opção, padrão *pastas por quantidade*):
  - `pastas`: `10x15/1 cópia/…`, `10x15/2 cópias/…` (sem subpasta se todas forem 1 cópia);
  - `nome`: `IMG_1234 (2 cópias).jpg`;
  - `repetir`: o arquivo gravado N vezes (`IMG_1234.jpg`, `IMG_1234 - 2.jpg`), para laboratórios que contam
    arquivos.
- **Nome**: o nome original sem extensão + `.jpg`; a mesma foto duas vezes no mesmo tamanho ganha ` - 2`; nunca
  sobrescreve.
- **JPEG**: `uint8`, qualidade 95, subamostragem 4:4:4, **baseline** (algumas máquinas de laboratório recusam
  progressivo), `dpi=(dpi, dpi)`, perfil sRGB embutido, EXIF mínimo: só a data original (sem GPS, sem orientação,
  sem miniatura). Gravação em `*.tmp` na mesma pasta + `os.replace`.
- **Resumo** `pedido.txt` na raiz da exportação: data, dpi, por tamanho o número de fotos e de cópias, o valor por
  cópia e o subtotal (quando houver preço; seção 13), o total estimado e a lista de arquivos com cópias. É o que a
  pessoa mostra ou envia ao laboratório.
- **Execução**: fila num `QThreadPool` (até `min(4, núcleos − 1)` em paralelo), cada tarefa
  `receita(original) → JPEG`; progresso por arquivo; cancelar termina o arquivo atual, apaga os `*.tmp` e informa
  o que ficou pronto. No fim: "Abrir a pasta" (`system.reveal`).
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
        {"tamanho": "20x30", "orientacao": "paisagem", "modo": "caber"}
      ]
    }
  ]
}
```

- `caminho` relativo à pasta do `.revelador` (com `/`) quando a foto está no mesmo disco; `caminho_absoluto` como
  reserva. Foto não encontrada: o app oferece "Procurar…" e reaproveita a pasta para as outras.
- Gravação segura (temporário + `os.replace`). **Recuperação**: autossalvamento a cada 2 min em
  `%LOCALAPPDATA%\Revelador\recuperacao\`; na abertura depois de uma falha, oferece recuperar.
- O `.msi` associa `.revelador` ao app (a #9 acrescenta o recurso `AssociacaoRevelador` no `.wxs`).

## 10. Interface

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ [Importar] [Exportar para revelação]   Tamanho padrão [10x15 ▾]   Mostrar [Todas|Selecionadas] │
├────────────────┬───────────────────────────────────────────────┬──────────────────────────┤
│ Grade de        │  Editor: a foto com a moldura do papel          │ Painel lateral           │
│ miniaturas      │  · fora do papel escurecido                     │ ▸ Impressões             │
│ ☑ marca         │  · margem de corte tracejada                    │   10x15 ×2  (retrato) ✎  │
│ 10x15 ×2        │  · aviso de resolução                            │   + Adicionar tamanho    │
│ ⚠ resolução     │  [↻ 90°] [Endireitar ──●──] [Automático]        │ ▸ Luz                    │
│                 │  [Antes/depois]                                  │ ▸ Cor                    │
│                 │                                                  │ ▸ Detalhe                │
├────────────────┴───────────────────────────────────────────────┴──────────────────────────┤
│ 37 fotos · 12 selecionadas · 10x15: 15 cópias · 20x30: 1 cópia · Total estimado: R$ 34,40     │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Grade** (`ui/grade.py`, `QListView` + modelo próprio, miniaturas sob demanda): marca de seleção, tamanho e
  cópias de cada foto, aviso de resolução. Seleção múltipla para aplicar tamanho, cópias ou ajustes de uma vez.
- **Editor** (`ui/editor.py`, `QGraphicsView` ou widget próprio): arrastar move o recorte, roda do mouse dá zoom,
  alças nos cantos mudam o zoom mantendo a proporção; botões de giro, endireitar, "Automático" (volta ao recorte
  dos rostos) e antes/depois. Mostra os rostos detectados (opção) para entender o recorte.
- **Painel lateral** (`ui/painel_ajustes.py`): impressões da foto atual e grupos de ajustes gerados de
  `ajustes.PARAMS`; duplo clique no controle volta ao padrão.
- **Atalhos**: Espaço marca/desmarca · ←/→ foto anterior/próxima · Ctrl+Z/Ctrl+Y desfazer/refazer · R gira 90° ·
  `\` antes/depois · Ctrl+C/Ctrl+V copiar/colar ajustes · + / − cópias · Ctrl+E exportar · Ctrl+S salvar ·
  Ctrl+O abrir · A recorte automático.
- **Arrastar e soltar** fotos e pastas na janela importa (recursivo, só formatos suportados).
- **Preferências** (`ui/prefs.settings()`): `QSettings` no registro (`HKCU\Software\Revelador\Revelador`) ou, com
  `REVELADOR_SETTINGS_DIR`, num `.ini`. Guarda geometria da janela, últimas pastas, tamanho padrão, dpi, modo de
  cópias e a verificação de atualizações.
- **Erros**: `crashlog.py` instala `sys.excepthook` e `threading.excepthook`, grava em
  `%LOCALAPPDATA%\Revelador\logs\` e mostra uma mensagem curta com "Abrir registro".

## 11. Atualização automática

`updater.py` é o mesmo desenho do PeliculaConverter (`pelicula/updater.py`), só para o Windows por enquanto:

- `REPO = "edvitor13/revelador"`; consulta `releases/latest` (pre-releases ficam de fora), compara
  `parse_version(tag)` com `__version__`.
- `install_info()` lê `revelador-install.json` ao lado do executável (`{"kind": "msi"|"zip", "version"}`); sem
  marcador num executável empacotado → `zip`; rodando do código-fonte → `source` (só mostra o link).
- `PATTERNS = {"msi": r"-windows-x64\.msi$", "zip": r"-windows-x64\.zip$"}` escolhe o pacote da release.
- `download()` exige o `SHA256SUMS.txt` da release e confere o SHA-256 antes de qualquer coisa.
- `install()` escreve um `.ps1` que espera o app fechar, roda `msiexec /i … /passive /norestart` (msi) ou
  `robocopy /MIR` da pasta extraída (zip, recusando caminhos absolutos ou com `..`), e reabre o app por
  `ProcessStartInfo` com `UseShellExecute = false`. O PowerShell sobe com `CREATE_NO_WINDOW` (nunca
  `DETACHED_PROCESS`, que faz o PowerShell sair sem rodar o script quando o pai não tem console). Registro em
  `atualizar.log` e `instalar.log` na pasta do download.
- Interface: verificação ao abrir, no máximo uma vez por dia, silenciosa sem internet (preferência para
  desligar); diálogo com as notas da versão, "Instalar e reiniciar", "Depois" e "Pular esta versão"; item
  "Procurar atualizações" no menu Ajuda.

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
  o mesmo papel e o mesmo preço somam na mesma linha.
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

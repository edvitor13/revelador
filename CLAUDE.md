# CLAUDE.md

Leia **[AGENTS.md](AGENTS.md)** antes de mudar qualquer coisa: lá estão o estado atual, o mapa dos módulos, as
regras que não podem ser quebradas, como rodar e testar e as receitas (tamanho de revelação, ajuste, enquadramento,
formato do trabalho, dependência). O desenho técnico completo (receita única, enquadramento pelos rostos, ajustes,
exportação, formato `.revelador`, atualização) está em [docs/ARQUITETURA.md](docs/ARQUITETURA.md). O que fazer e em
que ordem está nas issues do marco **0.1.0** no GitHub (`gh issue list --milestone 0.1.0`).

## O essencial

- **Originais intocáveis**: o app nunca grava, move, renomeia nem apaga a foto original. Tudo vive no trabalho
  (`.revelador`) e na exportação, numa pasta escolhida e sem sobrescrever nada.
- **Mesmo caminho para prévia e exportação**: toda imagem mostrada ou gravada passa pela receita única
  (`receita.py`: carregar → orientar → sRGB → girar/endireitar → recortar → redimensionar → ajustes → borda).
  Quem chama só muda o tamanho de destino. Nunca implemente um ajuste só na prévia ou só na exportação.
- **Ajustes são funções puras** de (imagem float32 0..1, valores), sem estado, sem `random`/`time`; raios e
  distâncias relativos ao tamanho da imagem de saída (ou em mm de papel convertidos pelo dpi).
- **Proporção do papel é lei**: o recorte tem exatamente a proporção do tamanho escolhido e a exportação sai com
  os px exatos do papel (mm → px pelo dpi, 300 por padrão). Tabela única em `tamanhos.py`.
- **Enquadramento automático é sugestão**: rostos (YuNet, `cv2.FaceDetectorYN`) definem só o recorte inicial;
  depois que a pessoa mexe, o recorte é manual e nunca é refeito sozinho. Sem rosto: centro.
- **Cor**: converter pelo perfil ICC embutido para sRGB ao carregar; exportar JPEG sRGB com perfil, dpi gravado,
  orientação já aplicada, qualidade 95 e 4:4:4.
- **Interface fluida**: decodificar, miniaturas, rostos, prévia e exportação fora da thread principal; Qt de
  interface só na thread principal; prévia sobre cópia reduzida (proxy) com *debounce*.
- **IDs e chaves nunca mudam** (`ajustes.PARAMS`, `tamanhos.TAMANHOS`, campos do `.revelador`); parâmetro novo
  com padrão neutro (0 = foto idêntica).
- **Texto do usuário em PT-BR com acentos, sempre por `_()`**; chaves e identificadores sem acento.
- **Dinheiro em centavos inteiros** (`precos.py`): nunca `float`; tamanho sem preço deixa o total parcial, nunca zero.
- **Dependências**: só PySide6, numpy, Pillow, pillow-heif e opencv-python-headless em tempo de execução.
- **Windows primeiro, código portável** (`pathlib`, `system.open_path()`/`reveal()`); só Windows no CI por ora.
- **Não sujar o ambiente do usuário** (preferências só por `ui/prefs.settings()`; testes com pastas temporárias;
  widgets do Qt em teste só num subprocesso *offscreen*). Nada de fotos pessoais no repositório.

## Comandos

```bash
instalar.bat                                 # cria .venv (py -3.15) e instala requirements.txt
.venv\Scripts\python -m pytest -q            # testes
.venv\Scripts\pythonw Revelador.pyw          # abrir o app (ou executar.bat)
.venv\Scripts\python -m revelador --diagnostico saida.json   # confere as dependências nativas
build.bat                                    # executável + .zip e .msi (.msi só se houver WiX)
```

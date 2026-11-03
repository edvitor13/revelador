<!-- Briefing comum dos agentes de implementação. O orquestrador manda cada agente ler este arquivo primeiro
     e escreve no prompt só a tarefa (issue, branch, arquivos, testes). Mantenha-o curto e atualizado. -->

# Briefing comum — agentes do Revelador

Você implementa UMA parte do Revelador (app PySide6 que prepara fotos para revelação; repositório
github.com/edvitor13/revelador). Outros agentes trabalham em paralelo em outras partes; um integrador junta tudo.

## Antes de codar
- Leia `CLAUDE.md` (curto) e, do `AGENTS.md`, só as regras e receitas citadas na sua tarefa. Da
  `docs/ARQUITETURA.md`, só as seções citadas (use Grep/offset; não leia arquivos grandes inteiros à toa).
- `gh issue view <n>` mostra a issue completa da sua tarefa.
- O modelo de dados comum já existe: `revelador/projeto.py` (Rosto, Recorte, Impressao, Foto, Trabalho) e
  `revelador/i18n.py` (`_()`, `N_()`). Use esses tipos; não os redefina.
- Módulos prontos (leia a docstring do módulo e as assinaturas, não o arquivo inteiro): `tamanhos.py`, `precos.py`,
  `imagem.py` (carregar, proxy, InfoFoto), `miniaturas.py`, `rostos.py`, `enquadramento.py` (`retangulo`,
  `recorte_sugerido`, `reencaixar`), `ajustes.py` (`PARAMS`, `aplicar`), `projeto.py` (também `salvar`/`abrir`),
  `updater.py`, `system.py`, `crashlog.py`, `ui/prefs.py`, `ui/main_window.py`, `receita.py` (`renderizar`,
  `tamanho_exportacao`, `carregar_fonte`, `para_uint8`), `ui/grade.py`, `ui/tarefas.py`, `ui/painel_impressoes.py`,
  `ui/precos_dialog.py`, `ui/resumo.py`, `ui/editor.py`, `ui/previa.py`.
- **Visual** (o app tem identidade própria, escura e moderna): use os nomes de objeto da folha de estilo de
  `ui/tema.py` (`Primary`, `Flat`, `Danger`, `Card`, `PanelTitle`, `Muted`, `Faint`, `Kicker`...), os componentes
  de `ui/componentes.py` (`Card`, `Slider`, `Segmented`, `ToggleSwitch`) e os ícones de `ui/icones.py`. **Nenhuma
  cor fixa fora de `tema.py`** (use as constantes). Confira a sua tela com `tools/captura_tela.py` (plataforma
  `windows`; `offscreen` não tem fontes) e OLHE o PNG com a ferramenta de leitura antes de entregar.
- **Ações da janela** (contrato): `acao_novo`, `acao_abrir`, `acao_salvar`, `acao_salvar_como`, `menu_recentes`,
  `acao_verificar_atualizacoes`, `acao_exportar`, `acao_importar`, `acao_importar_pasta`, `acao_desfazer` (Ctrl+Z),
  `acao_refazer` (Ctrl+Y / Ctrl+Shift+Z), `acao_configuracoes` ("Configurações…", engrenagem) e `acao_boas_vindas`
  ("Tela de boas-vindas", engrenagem) já existem na `MainWindow`, desligadas quando não têm dono. Conecte e ligue as
  da sua tarefa; **não crie menus nem botões de barra** (a barra superior só posiciona essas ações).
- **Ganchos comuns do `Estado`** (já existem): `visiveis` (ids das fotos visíveis na grade, na ordem dela; a grade
  publica por `definir_visiveis`) e `vizinha(passo)` (foto anterior/seguinte entre as visíveis); `lote(texto)`
  (*context manager*: agrupa mudanças em várias fotos num passo só do desfazer — use-o sempre que mexer em várias
  fotos de uma vez); `alterar_pastas()` + sinal `pastas_mudaram()` (quem muda `trabalho.pastas` chama;
  entra no desfazer). Modelo: `projeto.Pasta`, `Trabalho.pastas` e `Impressao.pasta` (pastas de tamanho, #32).
- **Interface**: todo widget conversa só pelo `revelador/ui/estado.py` (`janela.estado`): leia a docstring dele
  antes de qualquer widget. Mexeu no modelo → chame `estado.alterar(foto, pedido=...)`; nunca um widget chama outro.
  Não mude a API do `Estado` (pode ACRESCENTAR métodos se precisar; descreva no relatório).
- Na `MainWindow`, ligue a sua parte num método próprio `_ligar_<parte>()` chamado no fim do `__init__` (outros
  agentes fazem o mesmo; isso evita conflito no merge).

## Ambiente
- Você está numa **worktree git isolada** (seu diretório atual). Trabalhe só nela.
- Python com todas as dependências: `C:\Users\VitorGabriel\Desktop\DEV\revelador\.venv\Scripts\python.exe`.
  Rode a partir da sua worktree: `<esse python> -m pytest -q`. **Não instale pacotes.** Se achar uma dependência
  nova indispensável, pare e explique no relatório.
- Dependências disponíveis: PySide6 6.12, numpy 2.5, Pillow 13, pillow-heif 1.8, opencv-python-headless 5.0,
  pytest. Python 3.15. Windows.

## Arquivos
- Crie/edite **só os arquivos listados na sua tarefa** (mais testes novos seus em `tests/`).
- **Não edite** (o integrador cuida): `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, `README.md`, `docs/`,
  `requirements.txt`, `pyproject.toml`, `Revelador.spec`, `.github/`, `tests/conftest.py`, `revelador/i18n.py` e
  `revelador/projeto.py` (exceto se a sua tarefa disser o contrário).
- Se a implementação mostrar que a arquitetura precisa mudar (nome de função, número, decisão), siga o que fizer
  sentido e **descreva no relatório** — o integrador atualiza os docs.

## Regras do código
- PT-BR em docstrings, comentários e textos; identificadores sem acento; `from __future__ import annotations`;
  tipagem moderna (`X | None`); linhas de até ~120 colunas.
- Todo texto visível ao usuário por `_()`; tabelas montadas na importação com `N_()`.
- Funções puras onde a arquitetura pede; nada de `random`/`time` em cálculo de imagem.
- Testes com pytest. Imagens de teste **geradas no código** (Pillow/numpy) — nada de fotos pessoais. Widgets do Qt
  **só em subprocesso offscreen** (`from conftest import rodar_python`, veja `tests/test_app.py`); nunca crie
  `QApplication` no processo do pytest. A `conftest.py` já redireciona `REVELADOR_SETTINGS_DIR`, `LOCALAPPDATA`
  e `APPDATA` para pastas temporárias.
- No fim, a suíte inteira tem de passar (`-m pytest -q`).
- **Privacidade**: nunca envie dados do usuário (e-mail, nome, caminhos de arquivos) a serviços externos. Se uma
  requisição precisar de User-Agent, use só `Revelador-dev (github.com/edvitor13/revelador)`.
- Interface: nada de diálogo modal (`exec()`) em teste; telas testáveis por métodos/atributos públicos; trabalho
  pesado (decodificar, rostos, prévia) em `QThreadPool` com resultado por sinal na thread principal.

## Git e entrega
- `git switch -c <branch da sua tarefa>`; commits em PT-BR no estilo `Assunto: detalhe (#n)`, terminando com a
  linha de coautoria que as suas instruções de sistema mandam.
- `git push -u origin <branch>` e abra o PR: `gh pr create --base main --title "<título> (#n)" --body-file <arq>`.
  Corpo curto: o que foi feito, testes, o que fica para a interface; escreva "Parte de #n" (não "Closes"); termine
  com a linha `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. **Não faça merge.**

## Relatório final (até 15 linhas, sem colar código)
Branch, URL do PR, arquivos criados/alterados, número de testes novos e resultado da suíte, decisões ou desvios da
arquitetura que o integrador precisa refletir nos docs, e pendências.

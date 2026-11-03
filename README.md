<p align="center"><img src="assets/logo-256.png" width="128" alt="Revelador"></p>

<h1 align="center">Revelador</h1>

<p align="center">Escolha as fotos, confira o enquadramento no tamanho do papel e separe tudo para a revelação.</p>

---

> **Em construção (0.1.0).** O repositório já tem a documentação, o build e o instalador do Windows; as funções
> estão chegando pelas [issues do marco 0.1.0](https://github.com/edvitor13/revelador/milestone/1).

## Por que

Foto de celular é 4:3, 16:9 ou quadrada; o papel 10x15 é 2:3, o 13x18 é 5:7, o 20x25 é 4:5. Quando a foto vai
assim para o laboratório, a máquina corta o que sobra pelo meio — e às vezes leva junto uma cabeça ou a pessoa da
ponta. O Revelador mostra **exatamente o que vai sair no papel**, sugere um corte que **preserva os rostos** e
deixa você ajustar antes de enviar.

## O que ele vai fazer

- **Importar** fotos e pastas (JPEG, PNG, HEIC do iPhone, WebP, TIFF), com a orientação e a cor certas.
- **Selecionar** as fotos que vão para revelação, com **tamanho** e **quantidade de cópias** para cada uma
  (10x15, 13x18, 15x20, 15x21, 20x25, 20x30, A4, 30x40, 30x45, 40x60, quadradas e personalizado).
- **Enquadramento automático centrado nos rostos**, na proporção exata do papel, com aviso de resolução baixa.
- **Editor de enquadramento**: mover, aproximar, girar, endireitar, margem de corte do laboratório.
- **Ajustes no painel lateral**: exposição, contraste, realces, sombras, brancos, pretos, temperatura, matiz,
  saturação, vibração e nitidez, com antes/depois.
- **Exportar para revelação**: uma pasta por tamanho, JPEG sRGB a 300 dpi com os pixels exatos do papel e um
  resumo do pedido para o laboratório. As fotos originais nunca são alteradas.
- **Previsão de custos**: cadastre o valor de cada tamanho no seu laboratório e veja o total estimado do pedido.
- **Salvar o trabalho** para continuar depois e **atualização automática**.

Tudo roda no seu computador: nenhuma foto é enviada para lugar nenhum.

## Instalar

Quando a primeira versão sair, baixe em [Releases](https://github.com/edvitor13/revelador/releases):

- `Revelador-vX.Y.Z-windows-x64.msi` — instalador (por usuário, sem pedir administrador; atualiza sozinho);
- `Revelador-vX.Y.Z-windows-x64.zip` — versão portátil.

Windows 10 ou 11 (64 bits).

## Desenvolvimento

```bat
instalar.bat                              :: cria o .venv (Python 3.15) e instala as dependências
executar.bat                              :: abre o app
.venv\Scripts\python -m pytest -q         :: testes
build.bat                                 :: executável, .zip e (com o WiX) .msi
```

Antes de mexer no código, leia o [AGENTS.md](AGENTS.md) (regras, mapa e receitas) e a
[arquitetura](docs/ARQUITETURA.md). O CI (GitHub Actions) roda os testes em todo push e, no `main`, gera e testa o
instalador; uma tag `vX.Y.Z` publica a release.

## Licença

[MIT](LICENSE) © 2026 Vitor Gabriel. O modelo de detecção de rostos YuNet (OpenCV Zoo) é distribuído sob a licença
MIT.

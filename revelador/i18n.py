"""Textos traduzíveis.

Todo texto visível passa por ``_()`` na hora de aparecer, com placeholders nomeados
(``_("{n} cópias").format(n=...)``). Tabelas montadas na importação do módulo usam ``N_()`` (só marca o texto) e
são traduzidas com ``_()`` ao exibir. Por enquanto o app é só em PT-BR e as duas funções devolvem o texto como
está; a tradução (inglês e espanhol) entra depois sem mudar quem chama.
"""

from __future__ import annotations


def _(texto: str) -> str:
    """Texto traduzido para o idioma da interface (hoje: o próprio texto em PT-BR)."""
    return texto


def N_(texto: str) -> str:
    """Marca um texto para tradução sem traduzir agora (tabelas montadas na importação)."""
    return texto

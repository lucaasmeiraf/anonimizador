"""Base comum dos reconhecedores estruturados PT-BR.

Todos seguem o mesmo desenho: um ou mais padrões regex com score modesto,
uma lista de palavras-âncora para o enriquecedor de contexto do Presidio, e um
``validate_result`` que confirma ou derruba o candidato via checksum.

A semântica de ``validate_result`` no Presidio é o que dá a precisão alta:

* ``True``  -> o score vira 1.0 (evidência matemática, não heurística)
* ``False`` -> o resultado é descartado
* ``None``  -> mantém o score do padrão (para entidades sem checksum, como CEP)
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from presidio_analyzer import Pattern, PatternRecognizer


class ChecksumRecognizer(PatternRecognizer):
    """Reconhecedor de padrão com validação por dígito verificador."""

    def __init__(
        self,
        supported_entity: str,
        patterns: Sequence[Pattern],
        context: Sequence[str],
        validator: Optional[Callable[[str], bool]] = None,
        supported_language: str = "pt",
        name: Optional[str] = None,
    ) -> None:
        self._validator = validator
        super().__init__(
            supported_entity=supported_entity,
            patterns=list(patterns),
            context=list(context),
            supported_language=supported_language,
            name=name or f"{supported_entity}Recognizer",
        )

    def validate_result(self, pattern_text: str) -> Optional[bool]:
        if self._validator is None:
            return None
        return bool(self._validator(pattern_text))

"""La prise du suivi des erreurs hébergé : sans effet tant que la décision D4 n'est pas tranchée."""


def signale(exc: BaseException, request_id: str) -> None:
    """Signale une erreur inattendue au récepteur de suivi (aucun pour l'instant)."""

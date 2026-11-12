"""Les gardes de sécurité de l'API : origine (CSRF) et débit."""

# Les méthodes qui ne changent rien (RFC 9110 § 9.2.1, plus OPTIONS) : tout le reste est traité comme une
# écriture, une méthode inattendue (`PROPPATCH`, `TRACE`…) comprise.
METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS"})

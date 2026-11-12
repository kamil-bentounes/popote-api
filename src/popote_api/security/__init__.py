"""Ce qui décide qui est là et ce qu'il a le droit de faire : session, origine (CSRF), débit."""

# Les méthodes qui ne changent rien (RFC 9110 § 9.2.1, plus OPTIONS) : tout le reste est traité comme une
# écriture, une méthode inattendue (`PROPPATCH`, `TRACE`…) comprise.
METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS"})

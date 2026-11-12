
- Routes qui écrivent : `async def`, jamais `def` (le délai de 25 s ne peut pas annuler un fil) ; tout travail bloquant a un délai interne plus court que 25 s.

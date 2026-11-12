-- attendu : foyers en base, et la migration n'en connaît qu'un
-- Un second foyer : aucun `update` ni `insert` de 0114 ne filtre sur un foyer, donc
-- elle écrirait pour les deux.
insert into public.household (name) values ('Un second foyer');

-- attendu : paire(s) d'enveloppes aux libellés qui s'emboîtent
-- Deux enveloppes sans charge dont les libellés s'emboîtent (« Bricolage » et
-- « Bricolage et jardin »). La boucle de l'étape 4 lit un instantané : elle en
-- ferait deux charges, quand une enveloppe qui en contient une autre est, pour la
-- règle du doublon, une enveloppe à retirer.
insert into public.enveloppe (household_id, libelle, plafond_cents)
select h.id, x.libelle, x.plafond
from public.household h,
     (values ('Bricolage', 5001), ('Bricolage et jardin', 7003)) as x(libelle, plafond);

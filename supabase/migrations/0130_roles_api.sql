-- Les rôles de connexion de l'API (spec § 5.1). Compatible avec l'appli actuelle : elle ne s'en sert pas.
-- Aucun mot de passe ici : il est posé par environnement, depuis le gestionnaire de secrets.
-- Chaque rôle n'emprunte (SET ROLE) que le sien et n'hérite d'aucun droit : sans emprunt, il ne peut rien lire.
set local lock_timeout = '5s';
set local statement_timeout = '30s';

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'popote_api') then
    create role popote_api login noinherit nosuperuser nocreatedb nocreaterole noreplication;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'popote_internal') then
    create role popote_internal login noinherit nosuperuser nocreatedb nocreaterole noreplication;
  end if;
end $$;

grant authenticated to popote_api with inherit false, set true;
grant service_role to popote_internal with inherit false, set true;
grant usage on schema public to popote_api, popote_internal;

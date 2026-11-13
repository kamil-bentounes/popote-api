-- ═══════════════════════════════════════════════════════════════════════════
-- 0145 · EFFACER SES DONNÉES (T14a ; spec § 4, § 7.7 ; B3, B7, B8, B9, B26)
--
--  - `public.efface_mes_donnees()` : le corps de `delete_my_account()` SANS `delete from auth.users`, plus : clés
--    HMAC du journal mises à null (B7), fermeture des sessions de l'API (`login_session`) et de GoTrue (B9, par
--    `private.ferme_les_sessions_auth`, 0141), événement `compte_supprime` (une fois). `security definer`,
--    `search_path = ''`, `execute` à `authenticated` seul. Idempotente : sans profil, elle ne fait que fermer les
--    sessions. Les lignes `idempotency_key` partent en cascade avec le profil (0135, B8). `invite_link.created_by`
--    et `accepted_by` passent à null (`on delete set null`, 0142, B8) : un lien accepté reste.
--  - `public.delete_my_account()` redéfinie : appelle `efface_mes_donnees()` puis supprime `auth.users`.
--
-- COMPATIBLE avec l'appli en ligne : c'est la seule migration de 0.4 qui touche un objet qu'elle appelle.
-- `supabase.rpc('delete_my_account')` garde la même signature (sans argument, `void`), `security definer`, le même
-- `search_path`, les mêmes droits (`execute` à `authenticated`, retirés à `public` et `anon`) et le même effet, plus
-- la fermeture des sessions et une ligne de journal. Prouvé par `tests/db` (`rgpd`, `charges`, `budget-*`) et par
-- `tests/integration/test_suppression_differentielle.py`. Sauvegarde de la prod avant l'application (§ 5.3).
--
-- RETOUR ARRIÈRE (corps de `delete_my_account` d'avant, recopié de 0112) :
--   drop function public.efface_mes_donnees();   -- après avoir redéfini delete_my_account ainsi :
--   create or replace function public.delete_my_account()
--   returns void
--   language plpgsql security definer set search_path = public, pg_temp
--   as $$
--   declare v_uid uuid := auth.uid(); v_hh uuid; ch uuid; m date; retirees uuid[] := '{}';
--   begin
--     if v_uid is null then
--       raise exception 'non authentifié' using errcode = 'insufficient_privilege';
--     end if;
--     select household_id into v_hh from public.user_profile where id = v_uid;
--
--     /* Le verrou du foyer AVANT la première écriture : la fonction écrit désormais
--        dans `saisie`, `cloture_choix` et `facture`. Sans lui, un départ pendant un
--        « Revenir dessus » s'interbloquait. */
--     perform public.verrou_du_foyer(v_hh);
--
--     /* Ses charges à lui seul s'en vont avec lui : plus personne ne les porte, et
--        elles resteraient dans le budget de Kamil comme une dépense sans propriétaire.
--        `retire_charge` fait le tri : les lignes des mois ouverts et leurs saisies
--        partent, la charge avec si elle n'a pas d'histoire ; sinon elle s'arrête, et
--        les mois clôturés, confirmés ou payés restent tels quels. AVANT la
--        suppression du profil : elle lit `current_household()`. Le dernier membre n'a
--        pas à le faire, le foyer entier part. */
--     if v_hh is not null and exists (select 1 from public.user_profile
--                                     where household_id = v_hh and id <> v_uid) then
--       for ch in
--         select c.id from public.charge c
--         where c.household_id = v_hh and c.archive_le is null
--           and exists (select 1 from public.charge_participant p
--                       where p.charge_id = c.id and p.user_profile_id = v_uid)
--           and not exists (select 1 from public.charge_participant p
--                           where p.charge_id = c.id and p.user_profile_id <> v_uid)
--       loop
--         perform public.retire_charge(ch, true);
--         retirees := retirees || ch;
--         /* `retire_charge` ne retire jamais un ajustement, et la charge qui a une
--            histoire s'archive : le recalage de son archivage vient de poser, sur le mois
--            courant, un ajustement qui porte les parts de la partante seule. Personne ne
--            le repartagerait (`refige_pour` ne lit que `modele`) : il compterait dans le
--            mois, dans le reste de personne. Ce qui n'est ni confirmé, ni réglé, ni dans
--            un mois clôturé part avec elle. */
--         delete from public.depense d
--         where d.charge_id = ch and d.confirme_le is null and d.regle_le is null
--           and not exists (select 1 from public.cloture k
--                           where k.household_id = v_hh and k.mois = d.mois);
--       end loop;
--     end if;
--
--     if v_hh is not null then
--       /* Le détail part, le total reste : les saisies des lignes dont il est le
--          seul à porter une part, dans tous les mois, clôturés compris. Le montant
--          confirmé de la ligne reste : c'est le fait comptable du mois. */
--       delete from public.saisie s
--       where s.household_id = v_hh
--         and exists (select 1 from public.depense_part p
--                     where p.depense_id = s.depense_id and p.user_profile_id = v_uid)
--         and not exists (select 1 from public.depense_part p
--                         where p.depense_id = s.depense_id and p.user_profile_id <> v_uid);
--
--       /* Son revenu part avec son compte (`revenu` en cascade) : son reste ne se
--          redirait plus. Il garde `versement_id` : c'est par lui que « Revenir
--          dessus » épargne son versement, l'argent restant dans la poche. */
--       update public.cloture_choix set reste_cents = null
--       where household_id = v_hh and user_profile_id = v_uid;
--     end if;
--
--     /* 0090 : ses comptes perso partent AVANT son profil. Supprimer le profil
--        mettait `titulaire_id` à null, ce que `compte_titulaire_coherent` refuse. */
--     delete from public.compte where genre = 'perso' and titulaire_id = v_uid;
--     delete from public.user_profile where id = v_uid;
--
--     if v_hh is not null
--        and not exists (select 1 from public.user_profile where household_id = v_hh) then
--       /* Le dernier membre : ses factures et ses lignes d'abord. La cascade
--          `household → charge` pourrait buter sur leur `restrict`, l'ordre des
--          cascades n'étant pas garanti. */
--       delete from public.facture where household_id = v_hh;
--       delete from public.depense where household_id = v_hh;
--       delete from public.household where id = v_hh;
--     elsif v_hh is not null then
--       /* Les mois OUVERTS se repartagent entre ceux qui restent : ses parts des
--          lignes ni confirmées ni réglées reviennent aux autres, au prorata de
--          leurs revenus. Un mois clôturé vaut son `reste_cents` : `refige_pour` ne le
--          touche pas, ni les lignes gelées (« le total reste »). Après la suppression
--          du profil : il pèse les membres PRÉSENTS. */
--       for m in select distinct d.mois from public.depense d where d.household_id = v_hh order by 1
--       loop
--         perform public.refige_pour(v_hh, m);
--       end loop;
--       /* Son départ peut retirer des mois suivis, s'il était le seul à avoir un
--          revenu : on recale chaque charge qui a des factures dans une année
--          ouverte. `recale_la_charge` ne lit pas `current_household()` — il n'y en
--          a plus. */
--       for ch in
--         select distinct f.charge_id from public.facture f
--         where f.household_id = v_hh
--           and not exists (select 1 from public.releve_annuel r
--                           where r.charge_id = f.charge_id and r.annee = f.annee)
--           and f.charge_id <> all (retirees)
--       loop
--         perform public.recale_la_charge(ch);
--       end loop;
--     end if;
--
--     delete from auth.users where id = v_uid;
--   end $$;
--   revoke execute on function public.delete_my_account() from public, anon;
--   grant execute on function public.delete_my_account() to authenticated;
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

create or replace function public.efface_mes_donnees()
returns void
language plpgsql security definer set search_path = ''
as $$
declare v_uid uuid := auth.uid(); v_hh uuid; v_existait boolean := false; ch uuid; m date; retirees uuid[] := '{}';
begin
  if v_uid is null then
    raise exception 'non authentifié' using errcode = 'insufficient_privilege';
  end if;
  select household_id, true into v_hh, v_existait from public.user_profile where id = v_uid;

  /* Le verrou du foyer AVANT la première écriture : la fonction écrit désormais
     dans `saisie`, `cloture_choix` et `facture`. Sans lui, un départ pendant un
     « Revenir dessus » s'interbloquait. */
  perform public.verrou_du_foyer(v_hh);

  /* Ses charges à lui seul s'en vont avec lui : plus personne ne les porte, et
     elles resteraient dans le budget de Kamil comme une dépense sans propriétaire.
     `retire_charge` fait le tri : les lignes des mois ouverts et leurs saisies
     partent, la charge avec si elle n'a pas d'histoire ; sinon elle s'arrête, et
     les mois clôturés, confirmés ou payés restent tels quels. AVANT la
     suppression du profil : elle lit `current_household()`. Le dernier membre n'a
     pas à le faire, le foyer entier part. */
  if v_hh is not null and exists (select 1 from public.user_profile
                                  where household_id = v_hh and id <> v_uid) then
    for ch in
      select c.id from public.charge c
      where c.household_id = v_hh and c.archive_le is null
        and exists (select 1 from public.charge_participant p
                    where p.charge_id = c.id and p.user_profile_id = v_uid)
        and not exists (select 1 from public.charge_participant p
                        where p.charge_id = c.id and p.user_profile_id <> v_uid)
    loop
      perform public.retire_charge(ch, true);
      retirees := retirees || ch;
      /* `retire_charge` ne retire jamais un ajustement, et la charge qui a une
         histoire s'archive : le recalage de son archivage vient de poser, sur le mois
         courant, un ajustement qui porte les parts de la partante seule. Personne ne
         le repartagerait (`refige_pour` ne lit que `modele`) : il compterait dans le
         mois, dans le reste de personne. Ce qui n'est ni confirmé, ni réglé, ni dans
         un mois clôturé part avec elle. */
      delete from public.depense d
      where d.charge_id = ch and d.confirme_le is null and d.regle_le is null
        and not exists (select 1 from public.cloture k
                        where k.household_id = v_hh and k.mois = d.mois);
    end loop;
  end if;

  if v_hh is not null then
    /* Le détail part, le total reste : les saisies des lignes dont il est le
       seul à porter une part, dans tous les mois, clôturés compris. Le montant
       confirmé de la ligne reste : c'est le fait comptable du mois. */
    delete from public.saisie s
    where s.household_id = v_hh
      and exists (select 1 from public.depense_part p
                  where p.depense_id = s.depense_id and p.user_profile_id = v_uid)
      and not exists (select 1 from public.depense_part p
                      where p.depense_id = s.depense_id and p.user_profile_id <> v_uid);

    /* Son revenu part avec son compte (`revenu` en cascade) : son reste ne se
       redirait plus. Il garde `versement_id` : c'est par lui que « Revenir
       dessus » épargne son versement, l'argent restant dans la poche. */
    update public.cloture_choix set reste_cents = null
    where household_id = v_hh and user_profile_id = v_uid;
  end if;

  /* 0090 : ses comptes perso partent AVANT son profil. Supprimer le profil
     mettait `titulaire_id` à null, ce que `compte_titulaire_coherent` refuse. */
  delete from public.compte where genre = 'perso' and titulaire_id = v_uid;
  delete from public.user_profile where id = v_uid;

  if v_hh is not null
     and not exists (select 1 from public.user_profile where household_id = v_hh) then
    /* Le dernier membre : ses factures et ses lignes d'abord. La cascade
       `household → charge` pourrait buter sur leur `restrict`, l'ordre des
       cascades n'étant pas garanti. */
    delete from public.facture where household_id = v_hh;
    delete from public.depense where household_id = v_hh;
    delete from public.household where id = v_hh;
  elsif v_hh is not null then
    /* Les mois OUVERTS se repartagent entre ceux qui restent : ses parts des
       lignes ni confirmées ni réglées reviennent aux autres, au prorata de
       leurs revenus. Un mois clôturé vaut son `reste_cents` : `refige_pour` ne le
       touche pas, ni les lignes gelées (« le total reste »). Après la suppression
       du profil : il pèse les membres PRÉSENTS. */
    for m in select distinct d.mois from public.depense d where d.household_id = v_hh order by 1
    loop
      perform public.refige_pour(v_hh, m);
    end loop;
    /* Son départ peut retirer des mois suivis, s'il était le seul à avoir un
       revenu : on recale chaque charge qui a des factures dans une année
       ouverte. `recale_la_charge` ne lit pas `current_household()` — il n'y en
       a plus. */
    for ch in
      select distinct f.charge_id from public.facture f
      where f.household_id = v_hh
        and not exists (select 1 from public.releve_annuel r
                        where r.charge_id = f.charge_id and r.annee = f.annee)
        and f.charge_id <> all (retirees)
    loop
      perform public.recale_la_charge(ch);
    end loop;
  end if;

  /* Ce que 0.4 ajoute, dans la même transaction. Chaque ligne se rejoue sans erreur quand il n'y a plus rien
     (nouvelle tentative après une panne d'Auth : le profil est déjà parti). */

  -- B7 : plus aucune clé de la personne dans le journal. Avant `compte_supprime`, qui n'en porte pas.
  update public.security_event set account_key = null, ip_hash = null
  where person_id = v_uid and (account_key is not null or ip_hash is not null);

  -- B8 : ses lignes d'idempotence partent avec son profil (`idempotency_key.person_id` en cascade, 0135).

  -- Ses sessions : celles de l'API (`login_session` ne part en cascade qu'avec `auth.users`, que cette fonction
  -- ne supprime pas) et celles de GoTrue (B9 : `auth.sessions`, `auth.refresh_tokens`).
  delete from public.login_session where person_id = v_uid;
  perform private.ferme_les_sessions_auth(v_uid);

  -- Une seule fois : la nouvelle tentative d'une suppression déjà faite n'écrit rien. `person_id` passera à
  -- null (clé étrangère) quand `auth.users` partira.
  if v_existait then
    perform private.ecrit_evenement('compte_supprime', v_uid);
  end if;
end $$;
revoke all on function public.efface_mes_donnees() from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.efface_mes_donnees() to authenticated;
comment on function public.efface_mes_donnees() is
  'Efface les données de la personne appelante (foyer, charges, sessions, clés du journal) SANS supprimer son compte Auth. Idempotente. Exécutable par authenticated seul.';

-- ── delete_my_account : mêmes signature, droits et effet pour l'appli en ligne ──────────────────────────────
create or replace function public.delete_my_account()
returns void
language plpgsql security definer set search_path = public, pg_temp
as $$
declare v_uid uuid := auth.uid();
begin
  if v_uid is null then
    raise exception 'non authentifié' using errcode = 'insufficient_privilege';
  end if;
  perform public.efface_mes_donnees();
  delete from auth.users where id = v_uid;
end $$;
revoke execute on function public.delete_my_account() from public, anon;
grant execute on function public.delete_my_account() to authenticated;

/**
 * Le gabarit des mails de Popote, porté de la maquette (`gabarits.py`) : des TABLES et des styles en ligne (les
 * messageries ne lisent rien d'autre), un bouton « bulletproof », des espaces qui ne coupent pas, la police de
 * l'appli quand le client la charge et Georgia sinon.
 *
 * Un mail = un HÉROS de couleur par famille (bleu : le congélateur ; encre : ce qui périme ; herbe : la semaine ;
 * sable : le budget), une carte de détail, et un pied qui dit pourquoi on le reçoit. Les textes arrivent en
 * texte brut dans un `Contenu` : tout passe par `echappe` ici, une seule fois, et le même `Contenu` donne aussi le
 * texte brut de repli.
 */
import { echappe, insecables } from './texte.ts'
import type { PointDuJour } from './types.ts'

export const FOND = '#F2F4EF', SURFACE = '#FBFCFA', ENCRE = '#1C2B23', DOUX = '#5D6E62', HERBE = '#2F5D45'
export const SAFRAN = '#E8A33D', OCRE = '#8F5A0D', BRUME = '#DCE2D6', SABLE = '#F6EAD2'
export const BLEU = '#3E6A84', BLEU_TEXTE = '#2C4A58', BLEU_FOND = '#DCE8EE'
const CREUX = '#9FB0A4'
const SERIF = "Fraunces, Georgia, 'Times New Roman', serif"
const SANS = "'Instrument Sans', -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

export type Famille = 'bleu' | 'encre' | 'herbe' | 'sable'
export type CouleurDePoint = 'bleu' | 'herbe' | 'safran' | 'creux'

export type LigneDeCarte = { point: CouleurDePoint; titre: string; sous: string; droite: string }

export type Contenu = {
  famille: Famille
  sujet: string
  preEntete: string
  /** Le coin en haut à droite : « mercredi 28 oct., 19 h ». */
  quand: string
  titre: string
  intro: string
  bouton: { texte: string; url: string }
  lien?: { texte: string; url: string }
  /** Une illustration en bandeau, tout en haut du héros (bleu, sable). */
  image?: { src: string; alt: string }
  /** Le plat en vignette (encre) : sa photo si on en a une, une pastille, une légende. */
  plat?: { photo: string | null; alt: string; pastille: string; legende: string }
  /** Les sept jours (herbe). */
  grille?: { court: string; num: number; midi: PointDuJour; soir: PointDuJour; premier: boolean }[]
  carte: { titre: string; lignes: LigneDeCarte[]; note?: string; legende?: boolean }
  /** « Tu reçois ce mail parce que le rappel « … » est activé pour toi. » */
  raison: string
  /** Le lien « Régler mes rappels ». */
  reglages: string
}

const COULEUR_DE_POINT: Record<CouleurDePoint, { c: string; plein: boolean }> = {
  bleu: { c: BLEU, plein: true }, herbe: { c: HERBE, plein: true }, safran: { c: SAFRAN, plein: true },
  creux: { c: CREUX, plein: false },
}

const POINT_DU_JOUR: Record<PointDuJour, CouleurDePoint> = {
  congelateur: 'bleu', frigo: 'herbe', autre: 'safran', vide: 'creux',
}

const COTE = `role="presentation" cellpadding="0" cellspacing="0" border="0"`

function bouton(texte: string, url: string, fond: string, encre: string): string {
  return `<table ${COTE} class="bouton"><tr>
<td style="border-radius:16px;background:${fond}"><a href="${echappe(url)}" style="display:inline-block;padding:16px 26px;font-family:${SANS};font-size:16px;line-height:20px;font-weight:700;color:${encre};text-decoration:none;border-radius:16px">${echappe(texte)}</a></td></tr></table>`
}

function lienSimple(texte: string, url: string, couleur: string): string {
  return `<a href="${echappe(url)}" style="display:inline-block;padding:14px 4px;font-family:${SANS};font-size:15px;font-weight:600;color:${couleur};text-decoration:underline;text-underline-offset:3px">${echappe(texte)}</a>`
}

function point(p: CouleurDePoint): string {
  const { c, plein } = COULEUR_DE_POINT[p]
  const style = plein ? `background:${c}` : `border:2px solid ${c};width:6px;height:6px`
  return `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;${style};vertical-align:middle"></span>`
}

function ligneDeCarte(l: LigneDeCarte): string {
  return `<tr>
<td width="22" valign="top" style="padding:14px 0 0">${point(l.point)}</td>
<td style="padding:10px 0;font-family:${SANS}"><div style="font-size:15px;font-weight:700;color:${ENCRE}">${echappe(l.titre)}</div><div style="font-size:14px;color:${DOUX};padding-top:2px">${echappe(l.sous)}</div></td>
<td align="right" style="padding:10px 0;font-family:${SERIF};font-size:20px;font-weight:600;color:${ENCRE};white-space:nowrap">${echappe(l.droite)}</td></tr>`
}

const NOTE: Record<Famille, { fond: string; encre: string }> = {
  bleu: { fond: BLEU_FOND, encre: BLEU_TEXTE },
  encre: { fond: FOND, encre: ENCRE },
  herbe: { fond: FOND, encre: HERBE },
  sable: { fond: SABLE, encre: '#6B4A14' },
}

function carte(c: Contenu): string {
  const lignes = c.carte.lignes.map(ligneDeCarte).join('')
  const note = c.carte.note
    ? `<div style="margin-top:12px;padding:14px 16px;border-radius:16px;background:${NOTE[c.famille].fond};font-family:${SANS};font-size:14px;line-height:21px;color:${NOTE[c.famille].encre}">${echappe(c.carte.note)}</div>`
    : ''
  const item = (p: CouleurDePoint, t: string) =>
    `<span style="display:inline-block;white-space:nowrap;margin:0 12px 0 0">${point(p)}&nbsp; ${t}</span>`
  const legende = c.carte.legende
    ? `<div style="font-family:${SANS};font-size:13px;line-height:22px;color:${DOUX};padding-top:8px">${item('bleu', 'congélateur')}${item('herbe', 'frigo')}${item('safran', 'autre chose')}${item('creux', 'rien de prévu')}</div>`
    : ''
  return `<tr><td style="padding-top:14px"><table ${COTE} width="100%" style="background:${SURFACE};border:1px solid ${BRUME};border-radius:22px">
<tr><td class="pad" style="padding:20px 24px"><div style="font-family:${SERIF};font-size:19px;font-weight:600;color:${ENCRE};padding-bottom:4px">${echappe(c.carte.titre)}</div>
<table ${COTE} width="100%">${lignes}</table>${legende}${note}</td></tr></table></td></tr>`
}

function grille(g: NonNullable<Contenu['grille']>): string {
  const cases = g.map(j => `<td width="14%" align="center" style="padding:0 2px"><table ${COTE} width="100%" style="background:${j.premier ? SABLE : SURFACE};border-radius:14px"><tr><td align="center" style="padding:10px 0 11px;font-family:${SANS}">
<div style="font-size:12px;color:${DOUX}">${echappe(j.court)}</div><div style="font-family:${SERIF};font-size:20px;font-weight:600;color:${ENCRE};padding:2px 0 6px">${j.num}</div>
${point(POINT_DU_JOUR[j.midi])}&nbsp;${point(POINT_DU_JOUR[j.soir])}</td></tr></table></td>`).join('')
  return `<table ${COTE} width="100%"><tr>${cases}</tr></table><div style="height:22px;line-height:22px">&nbsp;</div>`
}

/** Les couleurs du héros de chaque famille. */
const HEROS: Record<Famille, { fond: string; titre: string; intro: string; bouton: [string, string]; lien: string }> = {
  bleu: { fond: BLEU_TEXTE, titre: '#FFFFFF', intro: BLEU_FOND, bouton: [SAFRAN, ENCRE], lien: BLEU_FOND },
  encre: { fond: ENCRE, titre: FOND, intro: '#C9D4CC', bouton: [SAFRAN, ENCRE], lien: '#E3EEE7' },
  herbe: { fond: HERBE, titre: '#FFFFFF', intro: '#D7E5DC', bouton: [SAFRAN, ENCRE], lien: '#E3EEE7' },
  sable: { fond: SABLE, titre: ENCRE, intro: '#6B4A14', bouton: [ENCRE, '#FFFFFF'], lien: OCRE },
}

function heros(c: Contenu): string {
  const h = HEROS[c.famille]
  const image = c.image
    ? `<tr><td style="padding:0;border-radius:28px 28px 0 0;overflow:hidden"><img src="${echappe(c.image.src)}" width="560" alt="${echappe(c.image.alt)}" style="display:block;width:100%;max-width:560px;height:auto;border:0;border-radius:28px 28px 0 0"></td></tr>`
    : ''
  const pastille = c.plat
    ? `<span style="display:inline-block;padding:6px 12px;border-radius:999px;background:${SAFRAN};font-family:${SANS};font-size:13px;font-weight:700;color:${ENCRE}">${echappe(c.plat.pastille)}</span>
      <div style="padding-top:12px;font-family:${SANS};font-size:14px;line-height:20px;color:#B9C7BD">${echappe(c.plat.legende)}</div>`
    : ''
  const plat = c.plat
    ? (c.plat.photo
      ? `<table ${COTE}><tr>
    <td valign="top" width="132"><img src="${echappe(c.plat.photo)}" width="132" height="132" alt="${echappe(c.plat.alt)}" style="display:block;width:132px;height:132px;object-fit:cover;border-radius:20px;border:0"></td>
    <td valign="top" style="padding-left:18px">${pastille}</td></tr></table>`
      : `<table ${COTE}><tr><td valign="top">${pastille}</td></tr></table>`)
    : ''
  const haut = image ? 'padding:6px 28px 28px' : 'padding:28px 28px 28px'
  const lien = c.lien ? lienSimple(c.lien.texte, c.lien.url, h.lien) : ''
  return `<table ${COTE} width="100%" style="background:${h.fond};border-radius:28px">
${image}<tr><td class="pad" style="${haut}">
  ${plat}
  <h1 class="titre" style="margin:${plat ? '22px' : '0'} 0 0;font-family:${SERIF};font-size:34px;line-height:38px;font-weight:600;color:${h.titre};letter-spacing:-0.4px">${echappe(c.titre)}</h1>
  <p style="margin:12px 0 ${c.grille ? '20px' : '22px'};font-family:${SANS};font-size:16px;line-height:24px;color:${h.intro}">${echappe(c.intro)}</p>
  ${c.grille ? grille(c.grille) : ''}${bouton(c.bouton.texte, c.bouton.url, h.bouton[0], h.bouton[1])}
  ${lien}
</td></tr></table>`
}

/** Le mail en HTML. */
export function html(c: Contenu): string {
  return insecables(`<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>${echappe(c.sujet)}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=Instrument+Sans:wght@400;600;700&display=swap');
@media (max-width:480px){ .pad{padding-left:20px !important;padding-right:20px !important} .titre{font-size:28px !important;line-height:32px !important} }
</style></head>
<body style="margin:0;padding:0;background:${FOND};-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:${FOND}">${echappe(c.preEntete)}${'&#8199;&#65279;&#847;'.repeat(60)}</div>
<table ${COTE} width="100%" style="background:${FOND}"><tr><td align="center" style="padding:20px 10px 36px">
<table ${COTE} width="100%" style="max-width:560px">
<tr><td style="padding:4px 6px 18px">
  <table ${COTE} width="100%"><tr>
    <td style="font-family:${SERIF};font-size:24px;font-weight:600;color:${HERBE};letter-spacing:-0.3px">Popote<span style="color:${SAFRAN}">.</span></td>
    <td align="right" style="font-family:${SANS};font-size:13px;color:${DOUX}">${echappe(c.quand)}</td>
  </tr></table>
</td></tr>
<tr><td>${heros(c)}</td></tr>
${carte(c)}
<tr><td class="pad" style="padding:26px 24px 0;font-family:${SANS};font-size:13px;line-height:20px;color:${DOUX}">
  ${echappe(c.raison)} <a href="${echappe(c.reglages)}" style="color:${HERBE};font-weight:600;white-space:nowrap">Régler mes rappels</a><br>
  Popote, la cuisine et le budget de Kamil et Léa.
</td></tr>
</table></td></tr></table></body></html>`)
}

/** Le repli en texte brut : le même contenu, sans mise en page. */
export function texte(c: Contenu): string {
  const grille = c.grille
    ? '\n' + c.grille.map(j => `${j.court} ${j.num} : midi ${DIT[j.midi]}, soir ${DIT[j.soir]}`).join('\n') + '\n'
    : ''
  const lignes = c.carte.lignes.map(l => `- ${l.titre} : ${l.sous} (${l.droite})`).join('\n')
  return [
    `Popote. ${c.quand}`,
    '',
    c.titre,
    '',
    c.intro,
    grille,
    `${c.bouton.texte} : ${c.bouton.url}`,
    c.lien ? `${c.lien.texte} : ${c.lien.url}` : '',
    '',
    c.carte.titre,
    lignes,
    c.carte.note ? `\n${c.carte.note}` : '',
    '',
    `${c.raison} Régler mes rappels : ${c.reglages}`,
    'Popote, la cuisine et le budget de Kamil et Léa.',
  ].filter((l, i, a) => !(l === '' && a[i - 1] === '')).join('\n').trim() + '\n'
}

const DIT: Record<PointDuJour, string> = {
  congelateur: 'du congélateur', frigo: 'du frigo', autre: 'autre chose', vide: 'rien de prévu',
}

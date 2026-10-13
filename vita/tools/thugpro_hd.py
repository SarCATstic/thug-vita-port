#!/usr/bin/env python3
"""Prepare le pack HD tire de THUG Pro pour le port THUG1 Vita.

THUG Pro (mod de THUG2 PC) a redessine en x4 une partie de l'interface de
THUG1 : la police des noms de figures (newtrickfont_ug_dump_0) et une
cinquantaine de sprites (HUD, icones des themes). Ce script ne contient AUCUNE
donnee : il lit l'installation THUG Pro du joueur et ses donnees THUG1, verifie
que chaque image HD correspond EXACTEMENT a l'originale (rectangles x k, k
entier), la ramene en x2 (assez en 960x544, et 4 fois moins de memoire) et
l'ecrit au format brut que le jeu sait lire, avec les dimensions de planche de
l'originale. Le jeu garde donc toutes les tailles d'origine : seule l'image
change, et un fichier absent ou incoherent laisse l'original.

    python3 vita/tools/thugpro_hd.py THUG1_DATA THUGPRO_DIR SORTIE

  THUG1_DATA   dossier data/ du dump Xbox (fonts/, pre/)
  THUGPRO_DIR  installation THUG Pro (data/fonts, data/pre)
  SORTIE       dossier a copier sur la console dans ux0:data/thug/hd/

Format .hd : b'THD1', u32 k, u32 largeur, u32 hauteur, puis RGBA 8 bits, lignes
dans l'ordre de la memoire (celui de LoadVitaImgInto / CVitaFont::plat_load),
alpha tel que le jeu l'attend (0..0x80 pour les sprites, double pour les
polices).
"""
import os
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pre_scan import read_pre          # noqa: E402
from tex_xbx import lire_img           # noqa: E402

K_SORTIE = 2

# Sprites HD de thugpro_themes.prx (Themes/THUGPRO_NEW) -> sprite THUG1.
# Releves par comparaison d'images (etude du 2026-10-13) ; seuls les rapports
# entiers sont gardes (les paused_piece en x1,6 sont ecartes).
HUD = {
    'balancebar_thug': 'balancemeter', 'balancearrow_thug': 'balancearrow_glow',
    'specialbar_thug': 'specialbar', 'special_text_thug': 'special',
    'score_thug': 'score_small', 'fakie_icon_thug': 'fakie_icon',
    'nollie_icon_thug': 'nollie_icon', 'switch_icon_thug': 'switch_icon',
    'pressure_icon_thug': 'pressure_icon', 'sw_pressure_icon_thug': 'sw_pressure_icon',
}
# Dessin different de l'original (verifie a l'oeil sur planche, 2026-10-13) :
# THUG Pro a remplace ces logos, on garde ceux de THUG1.
EXCLUS = {'ns_sponsor', 'ss2_mainicon', 'ss3_sponsor', 'ss4_sponsor'}
ICONES_TOURNEES = {'fakie_icon_thug', 'nollie_icon_thug', 'switch_icon_thug',
                   'pressure_icon_thug', 'sw_pressure_icon_thug'}


def ecrire_hd(chemin, k, rgba):
    h, w = rgba.shape[:2]
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, 'wb') as f:
        f.write(b'THD1' + struct.pack('<III', k, w, h))
        f.write(np.ascontiguousarray(rgba, dtype=np.uint8).tobytes())


def reduire(rgba, w, h):
    """Reduction de qualite en alpha premultiplie (pas de halo noir)."""
    a = rgba.astype(np.float32)
    al = a[..., 3:4] / 255.0
    pm = np.concatenate([a[..., :3] * al, a[..., 3:4]], axis=2)
    canaux = [np.asarray(Image.fromarray(pm[..., i]).resize((w, h), Image.LANCZOS))
              for i in range(4)]
    out = np.stack(canaux, axis=2)
    al = np.clip(out[..., 3:4], 0, 255) / 255.0
    rgb = np.where(al > 1e-3, out[..., :3] / np.maximum(al, 1e-3), 0)
    return np.clip(np.concatenate([rgb, out[..., 3:4]], axis=2) + 0.5, 0, 255).astype(np.uint8)


def ecart(a, b):
    pa = a[..., :3].astype(np.float32) * a[..., 3:4] / 255
    pb = b[..., :3].astype(np.float32) * b[..., 3:4] / 255
    return float(np.abs(pa - pb).mean())


def sprites(thug1, thugpro, sortie):
    t1 = {}
    for prx in ('panelsprites.prx', 'Themes.prx'):
        for nom, data in read_pre(os.path.join(thug1, 'pre', prx)).items():
            if nom.lower().endswith('.img.xbx'):
                t1[os.path.basename(nom.replace('\\', '/')).lower()[:-8]] = data
    tp = {}
    for nom, data in read_pre(os.path.join(thugpro, 'data', 'pre', 'thugpro_themes.prx')).items():
        n = nom.replace('\\', '/').lower()
        if '/thugpro_new/' in n and n.endswith('.img.xbx'):
            tp[os.path.basename(n)[:-8]] = data
    faits = 0
    for nom_tp, data_tp in sorted(tp.items()):
        nom_t1 = HUD.get(nom_tp, nom_tp)
        if nom_t1 not in t1 or nom_t1 in EXCLUS:
            continue
        t, a = lire_img(t1[nom_t1])
        u, b = lire_img(data_tp)
        if a is None or b is None:
            print('  %-22s illisible' % nom_t1)
            continue
        ow, oh = t['orig'][0] or t['w'], t['orig'][1] or t['h']
        bw, bh = u['orig'][0] or u['w'], u['orig'][1] or u['h']
        # La zone utile n'est pas toujours en tete de la memoire (les .img
        # sont ranges de bas en haut : une image de 50 lignes dans une planche
        # de 64 occupe les 50 DERNIERES), et THUG Pro ne range pas toujours
        # ses images dans le meme sens. On essaie les deux alignements des
        # deux cotes, les retournements et, pour les icones de position, le
        # quart de tour ; on garde la meilleure correspondance.
        meilleur = None
        for haut_o in (True, False):
            orig = a[:oh, :ow] if haut_o else a[t['h'] - oh:, :ow]
            for haut_h in (True, False):
                hd = b[:bh, :bw] if haut_h else b[u['h'] - bh:, :bw]
                bases = [np.rot90(hd, 1), np.rot90(hd, 3)] if nom_tp in ICONES_TOURNEES else [hd]
                for base in bases:
                    for c in (base, base[::-1], base[:, ::-1], base[::-1, ::-1]):
                        ch, cw = c.shape[:2]
                        if cw % ow or ch % oh or cw // ow != ch // oh:
                            continue
                        k = cw // ow
                        amax_o, amax_h = int(orig[..., 3].max()), int(c[..., 3].max())
                        if amax_h and amax_o and amax_o <= 0x80 < amax_h:
                            c = c.copy()
                            c[..., 3] = (c[..., 3].astype(np.uint16) * amax_o // amax_h).astype(np.uint8)
                        e = ecart(orig, reduire(c, ow, oh))
                        if meilleur is None or e < meilleur[0]:
                            meilleur = (e, k, c, haut_o)
        if meilleur is None:
            print('  %-22s ecarte (rapport non entier)' % nom_t1)
            continue
        e, k, c, haut_o = meilleur
        if e > 80:
            print('  %-22s ecarte (dessin trop different, ecart %.1f)' % (nom_t1, e))
            continue
        planche = np.zeros((t['h'] * K_SORTIE, t['w'] * K_SORTIE, 4), np.uint8)
        hd2 = reduire(c, ow * K_SORTIE, oh * K_SORTIE)
        if haut_o:
            planche[:oh * K_SORTIE, :ow * K_SORTIE] = hd2
        else:
            planche[( t['h'] - oh ) * K_SORTIE:, :ow * K_SORTIE] = hd2
        ecrire_hd(os.path.join(sortie, nom_t1 + '.hd'), K_SORTIE, planche)
        faits += 1
        print('  %-22s %3dx%-3d x%d (source x%d, ecart %.1f)' % (nom_t1, ow, oh, K_SORTIE, k, e))
    return faits


def lire_fnt(chemin):
    d = open(chemin, 'rb').read()
    gen2 = struct.unpack_from('<I', d, 4)[0] == 1
    if gen2:
        n, H, B = struct.unpack_from('<III', d, 8)
        o, gs = 20, 6
    else:
        n, H, B = struct.unpack_from('<III', d, 4)
        o, gs = 16, 4
    gl = [list(struct.unpack_from('<Hh', d, o + i * gs)) for i in range(n)]
    o += gs * n
    tw, th = struct.unpack_from('<HH', d, o + 4)
    o += 16
    idx = np.frombuffer(d, np.uint8, tw * th, o)
    o += (tw * th + 3) & ~3
    pal = np.frombuffer(d, np.uint8, 1024, o).reshape(256, 4).copy()
    o += 1024 + 4
    for i in range(n):
        gl[i] += list(struct.unpack_from('<HHHH', d, o + i * 8))
    # Comme CVitaFont::plat_load : palette R,G,B,A, alpha double.
    a = pal[:, 3].astype(np.uint16)
    pal[:, 3] = np.where(a >= 0x80, 255, a * 2).astype(np.uint8)
    return dict(n=n, H=H, B=B, tw=tw, th=th, gl=gl, rgba=pal[idx].reshape(th, tw, 4))


def police(thug1, thugpro, sortie, nom, nom_hd):
    o = lire_fnt(os.path.join(thug1, 'fonts', nom + '.fnt.xbx'))
    h = lire_fnt(os.path.join(thugpro, 'data', 'fonts', nom_hd + '.fnt.xbx'))
    k = h['tw'] // o['tw']
    ok = (h['n'] == o['n'] and k >= 2 and h['tw'] == k * o['tw'] and h['th'] == k * o['th']
          and h['H'] == k * o['H'] and h['B'] == k * o['B'])
    if ok:
        for go, gh in zip(o['gl'], h['gl']):
            if go[1] != gh[1] or [k * v for v in (go[0],) + tuple(go[2:])] != [gh[0]] + gh[2:]:
                ok = False
                break
    if not ok:
        print('  police %-14s ecartee : %s ne correspond pas glyphe pour glyphe' % (nom, nom_hd))
        return 0
    planche = reduire(h['rgba'], o['tw'] * K_SORTIE, o['th'] * K_SORTIE)
    ecrire_hd(os.path.join(sortie, 'fonts', nom + '.hd'), K_SORTIE, planche)
    print('  police %-14s %dx%d x%d (source x%d, %d glyphes identiques)' % (
        nom, o['tw'], o['th'], K_SORTIE, k, o['n']))
    return 1


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    thug1, thugpro, sortie = sys.argv[1:]
    print('polices :')
    n = police(thug1, thugpro, sortie, 'newtrickfont', 'newtrickfont_ug_dump_0')
    print('sprites :')
    n += sprites(thug1, thugpro, sortie)
    print('%d fichiers dans %s -> a copier dans ux0:data/thug/hd/' % (n, sortie))


if __name__ == '__main__':
    main()

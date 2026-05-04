
ARMY_CAPACITY = {1:20,2:30,3:70,4:80,5:135,6:150,7:200,8:200,9:220,10:240,11:260,12:280,13:300,14:320,15:320,16:340,17:360,18:380}
META_BY_HDV = {
18: "HDV18 (380 troupes): Zap Lalo = Golem de lave x4 + Ballon x28 + Foudre x2 + Haste x4 + Rage x2. Dragbat = Dragon x10 + Bat Spell x4 + Rage x2 + Haste x2. Root Rider = Cavalier Racine x12 + Super Barbare x8 + Rage x3.",
17: "HDV17 (360 troupes): Zap Lalo = Golem de lave x4 + Ballon x26 + Foudre x2 + Haste x4. Dragbat = Dragon x9 + Bat Spell x4 + Rage x2.",
16: "HDV16 (340 troupes): Lalo = Golem de lave x3 + Ballon x22 + Rage x2 + Haste x3. Dragbat = Dragon x8 + Bat Spell x3.",
15: "HDV15 (320 troupes): Lalo = Golem de lave x3 + Ballon x20 + Rage x2 + Haste x3. Yeti Smash = Yeti x10 + PEKKA x2 + Bowler x8.",
14: "HDV14 (320 troupes): Lalo = Golem de lave x3 + Ballon x18 + Rage x2 + Haste x3. Witch Slap = Witch x8 + Golem x3 + Bowler x6.",
13: "HDV13 (300 troupes): Lalo = Golem de lave x2 + Ballon x18 + Rage x2. Queen Charge Lalo = Reine + Guerisseuse x4 + Lalo.",
12: "HDV12 (280 troupes): Lalo = Golem de lave x2 + Ballon x16. Queen Walk Dragon = Reine + Guerisseuse x4 + Dragon x8.",
11: "HDV11 (260 troupes): Queen Walk Hog = Reine + Guerisseuse x4 + Hog Rider x20. Dragon = Dragon x10 + Ballon x4.",
10: "HDV10 (240 troupes): GoHo = Golem x2 + Hog Rider x18 + Guerison x3. Lavaloon = Golem de lave x2 + Ballon x14.",
9: "HDV9 (220 troupes): GoWiPe = Golem x1 + Sorcier x10 + PEKKA x2. Hog Rider = Hog Rider x20 + Guerison x3.",
8: "HDV8 (200 troupes): Dragon = Dragon x6 + Rage x2. GoWi = Golem x1 + Sorcier x8 + PEKKA x1.",
7: "HDV7 (200 troupes): Dragon = Dragon x6 + Rage x2. Giant Healer = Geant x15 + Guerisseuse x2.",
}
def get_coc_context(hdv):
    return META_BY_HDV.get(hdv, f"HDV{hdv} ({ARMY_CAPACITY.get(hdv,200)} troupes)")

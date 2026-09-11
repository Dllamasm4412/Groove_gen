"""Frozen seeds for the frozen cell library.

W8 freeze (initial): 25 cells across calm, lofi, latin, rock, hiphop (1001-5005).
W9 addition: pop tiers 1-5 with seeds 6001-6005, rnb tiers 1-5 with seeds
7001-7005. All W8 seeds preserved unchanged.

DO NOT change existing seeds. Adding new families with new seed ranges is OK
provided no existing (family, tier) key is modified.
"""

FROZEN_SEEDS = {
    ("calm", 1): 1001,
    ("calm", 2): 1002,
    ("calm", 3): 1003,
    ("calm", 4): 1004,
    ("calm", 5): 1005,
    ("lofi", 1): 2001,
    ("lofi", 2): 2002,
    ("lofi", 3): 2003,
    ("lofi", 4): 2004,
    ("lofi", 5): 2005,
    ("latin", 1): 3001,
    ("latin", 2): 3002,
    ("latin", 3): 3003,
    ("latin", 4): 3004,
    ("latin", 5): 3005,
    ("rock", 1): 4001,
    ("rock", 2): 4002,
    ("rock", 3): 4003,
    ("rock", 4): 4004,
    ("rock", 5): 4005,
    ("hiphop", 1): 5001,
    ("hiphop", 2): 5002,
    ("hiphop", 3): 5003,
    ("hiphop", 4): 5004,
    ("hiphop", 5): 5005,
    ("pop", 1): 6001,
    ("pop", 2): 6002,
    ("pop", 3): 6003,
    ("pop", 4): 6004,
    ("pop", 5): 6005,
    ("rnb", 1): 7001,
    ("rnb", 2): 7002,
    ("rnb", 3): 7003,
    ("rnb", 4): 7004,
    ("rnb", 5): 7005,
}

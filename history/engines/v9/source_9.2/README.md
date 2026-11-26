# Zebrafish 9.2

9.2 uses the 9.1 four-head NNUE and avoids redundant check tests, exchange evaluation, board updates and stack probes. At 1+0.1 it scored 261 wins, 301 draws and 189 losses against 9.1 (+33.4 observed Elo). At 180+1 it scored 250 wins, 425 draws and 215 losses in 890 games (52.0%, +13.7 observed Elo, LLR +1.223). The one-second plus 0.1-second SPRT accepted H1 (LLR +2.961). The three-minute SPRT was closed as inconclusive at promotion. The 445 complete opening pairs gave a descriptive 95% Elo interval of +0.0 to +27.8. Both tests compared 0 versus +10 Elo at bounds of ±2.944. The games used one thread and 64 MiB hash per engine with reversed openings, books off and tablebases off.

From the project root run `./engines/versions/v9/source_9.2/build.ps1`. Keep `nnue-9.1.bin` beside `9.2.exe` and `9.2_gui.exe`.

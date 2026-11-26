# Local Lichess integration

`Zebrafish-Bot.cmd` runs the local supervisor; `Zebrafish-Bot.cmd -Check`
validates prerequisites without contacting Lichess. `Zebrafish-Bot-Setup.cmd`
stores a new token under the Git-ignored `local/config/lichess/config.yml`.
Existing credentials are copied privately, never embedded in source or reports.

The current checkout remains physically at `integrations/lichess-bot` while its
supervisor is running. The canonical third-party alias and root Git registration
are established by the approved directory migration. The supervisor lock and
original scheduled-task path are preserved to avoid duplicate bots.

`patches/local-bridge.patch` records only the four modified upstream source files;
it contains no credentials. `prepare.ps1` checks whether that patch is installed
and can apply it explicitly to the pinned upstream checkout. Installed environments
are preserved in place; fresh environments must be recreated, not renamed.

The template uses the current engine under `build/current`. Relative engine paths
are interpreted from the bot checkout. Account conversion, token creation,
automatic matchmaking and autostart are user actions and are not performed by
setup checks or tests. The existing account and challenge settings are preserved
in the private configuration.

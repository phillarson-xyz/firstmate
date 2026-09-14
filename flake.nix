{
  description = "Reproducible Firstmate toolchain and offline checker.";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/42f17a57f4f6e33b3de3dca0a2a5ea5233169d02";

  outputs =
    { self, nixpkgs }:
    let
      # This nixpkgs revision no longer supports Intel macOS.
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      perSystem =
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          source = pkgs.lib.cleanSource ./.;
          releases = builtins.fromJSON (builtins.readFile ./nix/releases.json);
          releasePackage = pkgs.callPackage ./nix/release-package.nix { };
          treehouse = releasePackage {
            pname = "treehouse";
            release = releases.treehouse;
          };
          no-mistakes = releasePackage {
            pname = "no-mistakes";
            release = releases.no-mistakes;
          };
          axi-tools = pkgs.callPackage ./nix/axi-tools.nix { };
          runtime =
            with pkgs;
            [
              bashInteractive
              coreutils
              curl
              diffutils
              findutils
              gawk
              git
              gh
              gnugrep
              gnused
              gnutar
              gzip
              jq
              nodejs_24
              openssh
              python3
              ripgrep
              tmux
            ]
            ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
              pkgs.procps
              pkgs.util-linux
            ];
          toolchain = pkgs.symlinkJoin {
            name = "firstmate-toolchain";
            paths = [
              axi-tools
              treehouse
              no-mistakes
            ]
            ++ runtime;
            # Firstmate selects BSD flags whenever uname reports Darwin.
            # Do not shadow those host contracts with GNU coreutils.
            postBuild = pkgs.lib.optionalString pkgs.stdenv.hostPlatform.isDarwin ''
              for host in /usr/bin/stat /bin/date; do
                tool=$(basename "$host")
                rm "$out/bin/$tool"
                ln -s "$host" "$out/bin/$tool"
              done
            '';
          };
          versions = axi-tools.versions // builtins.mapAttrs (_: value: value.version) releases;
          manifest = pkgs.writeText "firstmate-toolchain-versions.json" (builtins.toJSON versions);
          toolchain-check = pkgs.writeShellApplication {
            name = "firstmate-toolchain-check";
            runtimeInputs = [ toolchain ];
            text = ''
              exec ${pkgs.python3}/bin/python3 ${./nix/check_toolchain.py} --manifest ${manifest} --firstmate-root ${source} "$@"
            '';
          };
        in
        {
          packages = {
            inherit
              axi-tools
              treehouse
              no-mistakes
              toolchain
              toolchain-check
              ;
            default = toolchain;
          }
          // pkgs.lib.genAttrs (builtins.attrNames axi-tools.versions) (
            name:
            pkgs.runCommand "${name}-${versions.${name}}" { } ''
              mkdir -p "$out/bin"
              ln -s ${axi-tools}/bin/${name} "$out/bin/${name}"
            ''
          );
          devShell = pkgs.mkShell {
            packages = [
              toolchain
              toolchain-check
              pkgs.shellcheck
              pkgs.actionlint
              pkgs.perl
              pkgs.nixfmt
            ];
            # No shellHook: shell entry must not initialize repos, trust, or services.
          };
          checks = {
            toolchain =
              pkgs.runCommand "firstmate-toolchain-check" { nativeBuildInputs = [ toolchain-check ]; }
                ''
                  firstmate-toolchain-check > "$out"
                '';
            python-tests =
              pkgs.runCommand "firstmate-toolchain-nix-tests" {
                nativeBuildInputs = [
                  toolchain
                  pkgs.python3
                ];
              }
                ''
                  cd ${source}
                  python3 -m unittest tests/test_nix_toolchain.py
                  touch "$out"
                '';
          };
        };
    in
    {
      packages = forAllSystems (system: (perSystem system).packages);
      devShells = forAllSystems (system: {
        default = (perSystem system).devShell;
      });
      checks = forAllSystems (system: (perSystem system).checks);
      apps = forAllSystems (system: {
        check = {
          type = "app";
          program = "${(perSystem system).packages.toolchain-check}/bin/firstmate-toolchain-check";
        };
      });
    };
}

{
  lib,
  buildNpmPackage,
  nodejs_24,
  makeWrapper,
  git,
  gh,
}:
let
  manifest = builtins.fromJSON (builtins.readFile ./axi/package.json);
  entrypoints = {
    gh-axi = "gh-axi/dist/bin/gh-axi.js";
    tasks-axi = "tasks-axi/dist/bin/tasks-axi.js";
    quota-axi = "quota-axi/dist/bin/quota-axi.js";
    lavish-axi = "lavish-axi/dist/cli.mjs";
    chrome-devtools-axi = "chrome-devtools-axi/dist/bin/chrome-devtools-axi.js";
    chrome-devtools-mcp = "chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js";
  };
in
buildNpmPackage {
  pname = manifest.name;
  inherit (manifest) version;
  src = ./axi;
  nodejs = nodejs_24;
  npmDepsHash = "sha256-vuIPbQbfDCEKfR9MdnshtRBPGmAB2wDVmboifN2W9bM=";
  # The npm releases contain dist/build assets. Never execute lifecycle scripts.
  npmFlags = [ "--ignore-scripts" ];
  npmRebuildFlags = [ "--ignore-scripts" ];
  dontNpmBuild = true;
  nativeBuildInputs = [ makeWrapper ];
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/lib/firstmate-axi" "$out/bin"
    cp -R node_modules "$out/lib/firstmate-axi/"
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: entry: ''
        test -f "$out/lib/firstmate-axi/node_modules/${entry}"
        makeWrapper ${nodejs_24}/bin/node "$out/bin/${name}" \
          --add-flags "$out/lib/firstmate-axi/node_modules/${entry}" \
          --prefix PATH : ${
            lib.makeBinPath [
              nodejs_24
              git
              gh
            ]
          } \
          --set-default CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS 1 \
          ${lib.optionalString (name == "chrome-devtools-axi")
            ''--set-default CHROME_DEVTOOLS_AXI_MCP_PATH "$out/lib/firstmate-axi/node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js"''
          }
      '') entrypoints
    )}
    runHook postInstall
  '';
  passthru.versions = manifest.dependencies;
  meta = {
    description = "Pinned Firstmate axi CLIs and Chrome DevTools MCP transport";
    platforms = lib.platforms.unix;
  };
}

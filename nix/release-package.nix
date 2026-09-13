{
  lib,
  stdenvNoCC,
  fetchurl,
  makeWrapper,
  git,
  openssh,
  gh,
  bash,
  gnutar,
  gzip,
}:
{ pname, release }:
let
  system = stdenvNoCC.hostPlatform.system;
  licenseFile = fetchurl {
    url = "https://raw.githubusercontent.com/${release.repo}/v${release.version}/LICENSE";
    sha256 = release.licenseHash;
  };
  platforms = {
    aarch64-darwin = "darwin-arm64";
    x86_64-darwin = "darwin-amd64";
    aarch64-linux = "linux-arm64";
    x86_64-linux = "linux-amd64";
  };
in
stdenvNoCC.mkDerivation {
  inherit pname;
  inherit (release) version;
  src = fetchurl {
    url = "https://github.com/${release.repo}/releases/download/v${release.version}/${pname}-v${release.version}-${platforms.${system}}.tar.gz";
    sha256 = release.hashes.${system};
  };
  dontUnpack = true;
  # Preserve upstream binaries, including Darwin code signatures.
  dontFixup = true;
  nativeBuildInputs = [
    makeWrapper
    gnutar
    gzip
  ];
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/libexec" "$out/bin"
    tar -xzf "$src" -C "$out/libexec" ${pname}
    chmod +x "$out/libexec/${pname}"
    install -Dm644 ${licenseFile} "$out/share/licenses/${pname}/LICENSE"
    makeWrapper "$out/libexec/${pname}" "$out/bin/${pname}" \
      --prefix PATH : ${
        lib.makeBinPath [
          git
          openssh
          gh
          bash
        ]
      } \
      ${lib.optionalString (
        pname == "no-mistakes"
      ) "--set NO_MISTAKES_NO_UPDATE_CHECK 1 --set NO_MISTAKES_TELEMETRY 0"}
    runHook postInstall
  '';
  meta = {
    description = "Pinned upstream ${pname} binary; no installer or service activation";
    homepage = "https://github.com/${release.repo}";
    license = lib.licenses.mit;
    mainProgram = pname;
    platforms = builtins.attrNames platforms;
  };
}

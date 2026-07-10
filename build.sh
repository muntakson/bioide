#!/usr/bin/env bash
set -euo pipefail
# Build, package (.vsix, without the broken vsce), install into code-server, restart.
# 확장 빌드 → vsix 패키징 → code-server 설치 → 재시작.
cd "$(dirname "$0")"

VER="$(node -p "require('./package.json').version")"
echo "==> esbuild bundle"
node esbuild.mjs

echo "==> package ghbio-coscientist.vsix (v$VER)"
rm -rf .vsix-build && mkdir -p .vsix-build/extension
cp -r package.json README.md LICENSE.txt dist media modules .vsix-build/extension/
[ -d tutorials ] && cp -r tutorials .vsix-build/extension/ || true
cat > ".vsix-build/[Content_Types].xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="json" ContentType="application/json"/><Default Extension="js" ContentType="application/javascript"/>
<Default Extension="svg" ContentType="image/svg+xml"/><Default Extension="md" ContentType="text/markdown"/>
<Default Extension="sh" ContentType="text/plain"/><Default Extension="py" ContentType="text/plain"/>
<Default Extension="txt" ContentType="text/plain"/><Default Extension="map" ContentType="application/json"/>
<Default Extension="vsixmanifest" ContentType="text/xml"/></Types>
XML
cat > .vsix-build/extension.vsixmanifest <<XML
<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
<Metadata><Identity Language="en-US" Id="ghbio-coscientist" Version="$VER" Publisher="ghbio"/>
<DisplayName>GHBIO Co-Scientist</DisplayName><Description xml:space="preserve">scRNA-seq bioinformatics workbench</Description>
<Categories>Data Science,Other</Categories></Metadata>
<Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
<Dependencies/><Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/></Assets>
</PackageManifest>
XML
(cd .vsix-build && zip -r -q ../ghbio-coscientist.vsix "[Content_Types].xml" extension.vsixmanifest extension)
rm -rf .vsix-build

echo "==> install into code-server + restart"
"$HOME/.local/bin/code-server" --install-extension "$PWD/ghbio-coscientist.vsix" --force
systemctl --user restart ghbio-code
echo "==> done. Reload the browser tab at https://ghbiocosci.iotok.org"

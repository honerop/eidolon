{
  description = "Eidolon: Zig 0.16 educational video renderer with semantic scenes and LaTeX";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      pkgsFor = system: import nixpkgs { inherit system; };
      directorFor = system:
        let pkgs = pkgsFor system;
        in pkgs.stdenv.mkDerivation {
          pname = "eidolon-director";
          version = "0.3.0";
          src = ./.;
          nativeBuildInputs = [ pkgs.zig_0_16 ];
          dontConfigure = true;
          buildPhase = ''
            runHook preBuild
            export ZIG_GLOBAL_CACHE_DIR="$TMPDIR/zig-global-cache"
            export ZIG_LOCAL_CACHE_DIR="$TMPDIR/zig-cache"
            mkdir -p "$ZIG_GLOBAL_CACHE_DIR" "$ZIG_LOCAL_CACHE_DIR"
            zig build-exe src/main.zig -O ReleaseFast -lc -femit-bin=eidolon-director
            runHook postBuild
          '';
          installPhase = ''
            mkdir -p "$out/bin"
            cp eidolon-director "$out/bin/"
          '';
          meta.mainProgram = "eidolon-director";
        };
      appFor = system:
        let
          pkgs = pkgsFor system;
          director = directorFor system;
          python = pkgs.python3.withPackages (ps: [ ps.edge-tts ]);
          fonts = pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; };
          tex = pkgs.texliveSmall.withPackages (ps: [
            ps.standalone ps.preview ps.amsmath ps.amsfonts ps.xcolor
          ]);
        in pkgs.writeShellScriptBin "eidolon" ''
          set -euo pipefail
          export EIDOLON_DEFAULT_SPEC="${./examples/general-showcase.json}"
          export EIDOLON_EDUCATION_SOURCE="${./tools/education.py}"
          export EIDOLON_LATEX_SOURCE="${./tools/latex_assets.py}"
          export EIDOLON_PDFLATEX="${tex}/bin/pdflatex"
          export EIDOLON_PDFTOCAIRO="${pkgs."poppler-utils"}/bin/pdftocairo"
          export EIDOLON_EDGE_TTS="${python}/bin/edge-tts"
          export EIDOLON_ESPEAK="${pkgs.espeak-ng}/bin/espeak-ng"
          export EIDOLON_FFPROBE="${pkgs.ffmpeg}/bin/ffprobe"
          export EIDOLON_FFMPEG="${pkgs.ffmpeg}/bin/ffmpeg"
          export EIDOLON_RSVG="${pkgs.librsvg}/bin/rsvg-convert"
          export FONTCONFIG_FILE="${fonts}"
          export EIDOLON_WORK="$(mktemp -d)"
          if [ -z "''${XDG_CACHE_HOME-}" ] && [ ! -w "''${HOME:-/nonexistent}" ]; then
            export XDG_CACHE_HOME="$EIDOLON_WORK/cache"
            mkdir -p "$XDG_CACHE_HOME"
          fi
          trap 'rm -rf "$EIDOLON_WORK"' EXIT
          if [ "''${1-}" = "images" ]; then
            shift
            "${python}/bin/python3" "${./tools/media_assets.py}" "$@"
            exit 0
          fi
          if [ "''${1-}" = "inspect" ] || [ "''${1-}" = "init" ]; then
            "${python}/bin/python3" "${./tools/project_inspect.py}" "$@"
            exit 0
          fi
          project="''${1:-$EIDOLON_DEFAULT_SPEC}"
          output="''${2:-showcase.mp4}"
          "${python}/bin/python3" "${./tools/media_assets.py}" prepare "$project" "$EIDOLON_WORK/project.json" --attribution "$EIDOLON_WORK/attribution.json"
          "${director}/bin/eidolon-director" "$EIDOLON_WORK/project.json" "$output"
          if [ -f "$EIDOLON_WORK/attribution.json" ]; then
            cp "$EIDOLON_WORK/attribution.json" "''${output%.mp4}.attribution.json"
          fi
        '';
    in {
      packages = eachSystem (system: {
        default = appFor system;
        eidolon = directorFor system;
        director = directorFor system;
      });
      apps = eachSystem (system: {
        default = { type = "app"; program = "${appFor system}/bin/eidolon"; };
      });
      checks = eachSystem (system:
        let
          pkgs = pkgsFor system;
          director = directorFor system;
          app = appFor system;
        in {
          zig-director = director;
          assets = pkgs.runCommand "eidolon-assets-tests" {
            nativeBuildInputs = [ pkgs.python3 ];
          } ''
            cd ${./.}
            ${pkgs.python3}/bin/python -m unittest discover -s tests -p 'test_*.py' -v
            touch "$out"
          '';
          smoke = pkgs.runCommand "eidolon-zig-smoke" { } ''
            mkdir -p "$out"
            cd "$out"
            export EIDOLON_SKIP_TTS=1
            "${app}/bin/eidolon" "${./examples/babel-smoke.json}" smoke.mp4
            test -s smoke.mp4
            test -f smoke.srt
            "${app}/bin/eidolon" "${./examples/education-smoke.json}" education.mp4
            test -s education.mp4
            "${app}/bin/eidolon" "${./examples/latex-smoke.json}" latex.mp4
            test -s latex.mp4
            EIDOLON_SKIP_TTS=0 EIDOLON_OFFLINE_TTS=1 "${app}/bin/eidolon" "${./examples/babel-voice-smoke.json}" narration.mp4
            test -s narration.mp4
            test -s narration.srt
            ${pkgs.ffmpeg}/bin/ffprobe -v error -show_entries stream=codec_type -of csv=p=0 narration.mp4 | grep -qx audio
            ${pkgs.ffmpeg}/bin/ffprobe -v error -show_entries stream=codec_name -of csv=p=0 latex.mp4 | grep -q h264
          '';
        });
      devShells = eachSystem (system:
        let
          pkgs = pkgsFor system;
          python = pkgs.python3.withPackages (ps: [ ps.edge-tts ]);
        in {
          default = pkgs.mkShell {
            packages = [
              pkgs.zig_0_16 python pkgs.ffmpeg pkgs.librsvg
              (pkgs.texliveSmall.withPackages (ps: [
                ps.standalone ps.preview ps.amsmath ps.amsfonts ps.xcolor
              ]))
              pkgs."poppler-utils" pkgs.fontconfig
            ];
          };
        });
    };
}
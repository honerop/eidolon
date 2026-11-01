{
  description = "Eidolon: Babel-authored general video timeline and MP4 media compositor";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.babel.url = "github:honerop/babel";

  outputs = { self, nixpkgs, babel }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      pkgsFor = system: import nixpkgs { inherit system; };

      compilerFor = system:
        let pkgs = pkgsFor system;
        in pkgs.stdenv.mkDerivation {
          pname = "babelc";
          version = "0.3.1";
          src = babel;
          nativeBuildInputs = [ pkgs.rustc ];
          dontConfigure = true;
          buildPhase = ''
            runHook preBuild
            rustc --edition=2021 --crate-name babel_compiler --crate-type rlib -O src/lib.rs -o libbabel_compiler.rlib
            rustc --edition=2021 -O src/main.rs --extern babel_compiler=libbabel_compiler.rlib -L dependency=. -o babelc
            runHook postBuild
          '';
          installPhase = ''
            mkdir -p "$out/bin"
            cp babelc "$out/bin/babelc"
          '';
        };

      directorFor = system:
        let
          pkgs = pkgsFor system;
          compiler = compilerFor system;
        in pkgs.stdenv.mkDerivation {
          pname = "eidolon-director";
          version = "0.2.0";
          src = ./.;
          dontConfigure = true;
          nativeBuildInputs = [ compiler pkgs.rustc ];
          buildPhase = ''
            runHook preBuild
            ${compiler}/bin/babelc check director.babel
            ${compiler}/bin/babelc build director.babel -o eidolon
            runHook postBuild
          '';
          installPhase = ''
            mkdir -p "$out/bin"
            cp eidolon "$out/bin/eidolon-director"
          '';
          meta.mainProgram = "eidolon-director";
        };

      appFor = system:
        let
          pkgs = pkgsFor system;
          director = directorFor system;
          python = pkgs.python3.withPackages (ps: [ ps.edge-tts ]);
          fonts = pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; };
          tex = pkgs.texliveSmall.withPackages (ps: [ ps.standalone ps.preview ps.amsmath ps.amsfonts ps.xcolor ]);
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
          export EIDOLON_DIRNAME="${pkgs.coreutils}/bin/dirname"
          export FONTCONFIG_FILE="${fonts}"
          export BABEL_PROCESS_TIMEOUT_MS=1800000
          export EIDOLON_WORK="$(mktemp -d)"
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
        compiler = compilerFor system;
      });

      apps = eachSystem (system: {
        default = {
          type = "app";
          program = "${appFor system}/bin/eidolon";
        };
      });

      checks = eachSystem (system:
        let
          pkgs = pkgsFor system;
          director = directorFor system;
          app = appFor system;
        in {
          babel-director = director;
          assets = pkgs.runCommand "eidolon-assets-tests" { nativeBuildInputs = [ pkgs.python3 ]; } ''
            cd ${./.}
            ${pkgs.python3}/bin/python -m unittest discover -s tests -p 'test_*.py' -v
            touch "$out"
          '';
          smoke = pkgs.runCommand "eidolon-smoke" { } ''
            mkdir -p "$out"
            cd "$out"
            "${app}/bin/eidolon" "${./examples/babel-smoke.json}" "smoke.mp4"
            test -s smoke.mp4
            test -s smoke.srt
            ${pkgs.ffmpeg}/bin/ffprobe -v error -show_entries stream=codec_name,width,height -of json smoke.mp4 > info.json
            grep -q h264 info.json
            # Exercise every semantic educational scene through Babel and FFmpeg.
            "${app}/bin/eidolon" "${./examples/education-smoke.json}" "education-smoke.mp4"
            test -s education-smoke.mp4
            test -s education-smoke.srt
            # Render actual LaTeX formula assets, not a mocked raster image.
            "${app}/bin/eidolon" "${./examples/latex-smoke.json}" "latex-smoke.mp4"
            test -s latex-smoke.mp4
            test -s latex-smoke.srt
            ${pkgs.ffmpeg}/bin/ffprobe -v error -show_entries stream=codec_name -of csv=p=0 education-smoke.mp4 | grep -q h264
          '';
        });

      devShells = eachSystem (system:
        let
          pkgs = pkgsFor system;
          python = pkgs.python3.withPackages (ps: [ ps.edge-tts ]);
        in {
          default = pkgs.mkShell {
            packages = [
              (compilerFor system)
              python pkgs.ffmpeg pkgs.librsvg pkgs.rustc
              (pkgs.texliveSmall.withPackages (ps: [ ps.standalone ps.preview ps.amsmath ps.amsfonts ps.xcolor ])) pkgs."poppler-utils"
              pkgs.cargo pkgs.pkg-config pkgs.fontconfig
            ];
          };
        });
    };
}

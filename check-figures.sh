#!/usr/bin/env bash
# Find figure files not referenced by any txt/md/tex/typ file.
# Usage: check-figures.sh [root] [-e ext1,ext2,...] [-v]
#   -v  also flag references in .txt/.md/.tex/.typ that point to nonexistent figures
set -eu

root="."
fig_exts="png"
verbose=0

while [ $# -gt 0 ]; do
    case "$1" in
        -e) fig_exts="$2"; shift 2 ;;
        -v) verbose=1; shift ;;
        -h|--help)
            echo "Usage: $0 [root] [-e ext1,ext2,...] [-v]  (default exts: png)"
            exit 0 ;;
        *) root="$1"; shift ;;
    esac
done

[ -d "$root" ] || { echo "Not a directory: $root" >&2; exit 2; }

if command -v rg >/dev/null 2>&1; then
    search() { rg --no-messages -l -F "$1" -- "$2"; }
    list_refs_flags=(--no-messages --files -t txt -t md -t tex)
    # rg knows md/tex but not typ; add typ via glob
    list_refs() {
        rg --no-messages --files "$root" -g '*.txt' -g '*.md' -g '*.tex' -g '*.typ'
    }
else
    search() { grep -rlF -- "$1" "$2" 2>/dev/null; }
    list_refs() {
        find "$root" \( -name '*.txt' -o -name '*.md' -o -name '*.tex' -o -name '*.typ' \) -type f
    }
fi

# Build find expression for figure extensions
find_args=()
first=1
IFS=',' read -r -a exts <<< "$fig_exts"
for ext in "${exts[@]}"; do
    if [ $first -eq 1 ]; then
        find_args+=( -name "*.${ext}" )
        first=0
    else
        find_args+=( -o -name "*.${ext}" )
    fi
done

# Snapshot of candidate ref files (one list, reused)
ref_list=$(list_refs)
[ -z "$ref_list" ] && { echo "No referencing files (.txt/.md/.tex/.typ) under $root" >&2; }

orphans=0
while IFS= read -r -d '' fig; do
    base=$(basename "$fig")
    rel=${fig#"$root"/}
    found=0
    # Check each candidate ref file for basename or relative-path substring.
    while IFS= read -r ref; do
        [ -z "$ref" ] && continue
        # Skip self (shouldn't match since refs are text exts, but defensive)
        [ "$ref" = "$fig" ] && continue
        if grep -qF -e "$base" -e "$rel" -- "$ref" 2>/dev/null; then
            found=1
            break
        fi
    done <<< "$ref_list"
    if [ $found -eq 0 ]; then
        echo "$fig"
        orphans=$((orphans + 1))
    fi
done < <(find "$root" -type f \( "${find_args[@]}" \) -print0)

stale=0
if [ $verbose -eq 1 ]; then
    # Build a regex alternation of extensions for grep -E
    ext_alt=$(printf "%s" "$fig_exts" | tr ',' '|')
    # Index all figure basenames and relpaths for fast lookup
    fig_index=$(find "$root" -type f \( "${find_args[@]}" \) -print 2>/dev/null || true)

    while IFS= read -r ref; do
        [ -z "$ref" ] && continue
        ref_dir=$(dirname "$ref")
        # Extract candidate path tokens ending in a fig extension (best-effort).
        grep -oE "[A-Za-z0-9_./~+-]+\.($ext_alt)" "$ref" 2>/dev/null | sort -u | while IFS= read -r cand; do
            [ -z "$cand" ] && continue
            # Resolve candidate: try relative to ref's dir, then relative to root,
            # then match by basename anywhere in the figure index.
            if [ -f "$ref_dir/$cand" ] || [ -f "$root/$cand" ] || [ -f "$cand" ]; then
                continue
            fi
            cand_base=$(basename "$cand")
            if printf "%s\n" "$fig_index" | grep -qxF -- "$root/$cand_base" 2>/dev/null \
               || printf "%s\n" "$fig_index" | awk -v b="$cand_base" -F/ '$NF==b{f=1} END{exit !f}'; then
                continue
            fi
            echo "stale: $ref -> $cand"
        done
    done <<< "$ref_list"
fi

[ $orphans -eq 0 ] || exit 1

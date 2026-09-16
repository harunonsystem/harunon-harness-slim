#!/bin/bash
# 共有ライブラリ: 危険コマンド判定の前処理（コマンド文字列の標準化）
#
# 提供する関数:
#   normalize_command <command>
#     — 判定しやすい標準形を 1 行以上で echo する
#
# なぜ quote-aware lexer なのか:
#   旧実装（正規表現の連鎖）は「引用符の中身は実行されない文字列」を区別できず、
#   `echo "a; git push"` のような無害な文字列引数を誤検知したり、逆に
#   `git "push"` のような quote 分割で判定をすり抜けられたりしていた。
#   本実装は CODE / 単一引用 / 二重引用 / コマンド置換を字句解析で分解し、
#   quote の内側を「空白も演算子も持たない不活性テキスト」に中和したうえで、
#   コマンド置換・interpreter -c の中身だけを別行（コード）として抽出する。
#
# 契約: normalize_command の出力は判定専用の 1 行以上のテキストであり、実行は
#   しない。グルーピング文字を区切りに潰してよく、元コマンドの実行意味を
#   保つ必要はない。
#
# 扱わないこと（既知の限界）:
#   - quote は解決済み（本実装のスコープ）。残るのは heredoc 本体・遠隔実行
#     ラッパ（ssh/docker 等）・`$CMD` のような動的なコマンド名の復元・
#     pi/opencode の JS/TS 側との runtime 非対称（そちらは regex のみを通る）
#   - match.ere の table 化（IR 化フルスコープ）は見送り
#
# bash 3.2（macOS 標準）互換。文字列処理は perl に委ねる（bash での実装は
# quote / 改行の扱いで壊れやすく、review-gate.sh も同じ理由で perl を使っている）。

# perl 不在時は判定不能。呼び出し側が fail-closed に倒せるよう 1 を返す。
normalize_command_available() {
  command -v perl >/dev/null 2>&1
}

# perl 本体は quoted heredoc で保持する（perl -e '...' に直書きすると
# 単一引用符が '"'"' 連発になって読めなくなる）。
# NOTE: $(cat <<'PERL') 形式は使えない。bash は $( ) の中身を先読みして
# バッククォートの対応を取ろうとするため、perl 側の ` が unbalanced になる。
IFS= read -r -d '' _NORMALIZE_PERL <<'PERL' || true
use strict;
use warnings;

my $F = '~';
my $MAX_DEPTH = 5;

# 中和: quote の中身を「空白も演算子も持たない」トークンへ潰す。文字を消さず
# ~ に置換するのは、`git "push"` / `''git push` のような quote 分割回避を
# 「git push」へ畳んで deny させるため。保持集合は wordEndEre
# （([^A-Za-z0-9_/-]|$)）を満たす必要があるため区切りは `~` 固定（`_` にすると
# `git clean -fd""` が allow に後退する）。`+` を保持するのは
# `git push origin "+HEAD"`（強制 refspec）を判定に載せるため。
sub neutralize {
    my ($t) = @_;
    $t =~ s{[^A-Za-z0-9_./:=\@,+-]}{$F}g;
    return $t;
}

sub is_code_arg {
    my ($prefix) = @_;
    return 1 if $prefix =~ /(?:^|[\s;&|(~])(?:ba|z|da|k)?sh(?:\s+\S+)*?\s+-[A-Za-z]*c\s+$/;
    return 1 if $prefix =~ /(?:^|[\s;&|(~])eval\s+$/;
    return 0;
}

sub scan_sq {
    my ($src, $i, $ansi) = @_;
    my $body = '';
    my $n = length $src;
    while ($i < $n) {
        my $c = substr($src, $i, 1);
        if ($ansi && $c eq '\\' && $i + 1 < $n) { $body .= $F; $i += 2; next; }
        return ($body, $i) if $c eq "'";
        $body .= $c; $i++;
    }
    return (undef, undef);
}

sub scan_dq {
    my ($src, $i) = @_;
    my $body = '';
    my $n = length $src;
    while ($i < $n) {
        my $c = substr($src, $i, 1);
        if ($c eq '\\' && $i + 1 < $n) {
            my $x = substr($src, $i + 1, 1);
            $body .= ($x =~ /[\$"`\\\n]/) ? $F : $F . $x;
            $i += 2; next;
        }
        return ($body, $i) if $c eq '"';
        if ($c eq '$' && substr($src, $i + 1, 1) eq '(') {
            my ($sub, $end) = scan_paren($src, $i + 2);
            if (defined $end) { $body .= substr($src, $i, $end - $i + 1); $i = $end + 1; next; }
        }
        $body .= $c; $i++;
    }
    return (undef, undef);
}

sub scan_paren {
    my ($src, $i) = @_;
    my $depth = 1;
    my $start = $i;
    my $n = length $src;
    while ($i < $n) {
        my $c = substr($src, $i, 1);
        if ($c eq '\\') { $i += 2; next; }
        if ($c eq "'") { my (undef, $e) = scan_sq($src, $i + 1, 0); return (undef, undef) unless defined $e; $i = $e + 1; next; }
        if ($c eq '"') { my (undef, $e) = scan_dq($src, $i + 1);    return (undef, undef) unless defined $e; $i = $e + 1; next; }
        if ($c eq '(') { $depth++; $i++; next; }
        if ($c eq ')') { $depth--; return (substr($src, $start, $i - $start), $i) if $depth == 0; $i++; next; }
        $i++;
    }
    return (undef, undef);
}

sub push_code {
    my ($eref, $body, $depth) = @_;
    if ($depth >= $MAX_DEPTH) { push @$eref, "; " . $body; return; }
    my ($line, $extra) = render_code($body, $depth + 1);
    push @$eref, "; " . $line;
    push @$eref, @$extra;
}

sub render_dq_body {
    my ($body, $depth) = @_;
    my @extra;
    my $out = '';
    my $i = 0;
    my $n = length $body;
    while ($i < $n) {
        my $c = substr($body, $i, 1);
        if ($c eq '$' && substr($body, $i + 1, 1) eq '(') {
            my ($sub, $end) = scan_paren($body, $i + 2);
            if (defined $end) { push_code(\@extra, $sub, $depth); $out .= $F; $i = $end + 1; next; }
        }
        if ($c eq '`') {
            my $j = index($body, '`', $i + 1);
            if ($j >= 0) { push_code(\@extra, substr($body, $i + 1, $j - $i - 1), $depth); $out .= $F; $i = $j + 1; next; }
        }
        $out .= neutralize($c); $i++;
    }
    return ($out, \@extra);
}

sub emit_quoted {
    my ($lref, $eref, $body, $is_dq, $depth) = @_;
    if (is_code_arg($$lref)) { push_code($eref, $body, $depth); $$lref .= $F; return; }
    if ($is_dq) {
        my ($frag, $sub) = render_dq_body($body, $depth);
        push @$eref, @$sub;
        $$lref .= $frag;
        return;
    }
    $$lref .= neutralize($body);
}

sub render_code {
    my ($src, $depth) = @_;
    my $line = '';
    my @extra;
    my $i = 0;
    my $n = length $src;
    while ($i < $n) {
        my $c = substr($src, $i, 1);

        # バックスラッシュは特殊文字としての意味を消すだけで文字は残る。
        # \\git push は git を実行するので、語構成文字はそのまま判定に載せる。
        if ($c eq '\\') {
            my $x = substr($src, $i + 1, 1);
            $line .= ($x =~ m{[A-Za-z0-9_./-]}) ? $x : $F;
            $i += 2; next;
        }

        if ($c eq '#' && ($i == 0 || substr($src, $i - 1, 1) =~ /[\s;&|(]/)) {
            my $j = index($src, "\n", $i);
            $j = $n if $j < 0;
            $line .= $F;
            $i = $j;
            next;
        }

        if ($c eq "'" || ($c eq '$' && substr($src, $i + 1, 1) eq "'")) {
            my $ansi = ($c eq '$');
            my ($body, $end) = scan_sq($src, $i + ($ansi ? 2 : 1), $ansi);
            if (!defined $end) { $line .= $F; $i++; next; }
            emit_quoted(\$line, \@extra, $body, 0, $depth);
            $i = $end + 1; next;
        }

        if ($c eq '"') {
            my ($body, $end) = scan_dq($src, $i + 1);
            if (!defined $end) { $line .= $F; $i++; next; }
            emit_quoted(\$line, \@extra, $body, 1, $depth);
            $i = $end + 1; next;
        }

        if ($c eq '$' && substr($src, $i + 1, 1) eq '(') {
            my ($body, $end) = scan_paren($src, $i + 2);
            if (!defined $end) { $line .= $F; $i++; next; }
            push_code(\@extra, $body, $depth);
            $line .= $F;
            $i = $end + 1; next;
        }

        if ($c eq '`') {
            my $j = -1;
            for (my $k = $i + 1; $k < $n; $k++) {
                if (substr($src, $k, 1) eq '\\') { $k++; next; }
                if (substr($src, $k, 1) eq '`') { $j = $k; last; }
            }
            if ($j < 0) { $line .= $F; $i++; next; }
            push_code(\@extra, substr($src, $i + 1, $j - $i - 1), $depth);
            $line .= $F;
            $i = $j + 1; next;
        }

        $line .= $c; $i++;
    }
    return ($line, \@extra);
}

# P0-A: git のグローバルオプション列を落として subcommand を git に隣接させる
# generic 版（旧: allowlist 化した固定パターンの列挙）。値を取るオプション集合は
# enforce-gwm-for-worktree.sh の options_with_values（python 側の判定）と
# 一致させること。判定ロジックが perl / python の 2 箇所に分かれるので、
# どちらかを変えたらもう片方も見直す。
my %GIT_VALUE_OPTS = map { $_ => 1 } (
    '-C', '-c', '--config-env', '--exec-path', '--git-dir', '--namespace',
    '--super-prefix', '--work-tree',
);

sub strip_git_global_options {
    my ($s) = @_;
    my $n = length $s;
    my $out = '';
    my $i = 0;
    while ($i < $n) {
        my $boundary_before = ($i == 0) || (substr($s, $i - 1, 1) !~ /[A-Za-z0-9_]/);
        if ($boundary_before && substr($s, $i, 3) eq 'git'
            && ($i + 3 == $n || substr($s, $i + 3, 1) !~ /[A-Za-z0-9_]/)) {
            $out .= 'git';
            my $j = $i + 3;
            OPTION_TOKEN: while (1) {
                my $k = $j;
                $k++ while $k < $n && substr($s, $k, 1) =~ /[ \t]/;
                last OPTION_TOKEN if $k == $j; # 直後に空白が無ければ隣接語なので触らない

                my $tstart = $k;
                $k++ while $k < $n && substr($s, $k, 1) !~ /[ \t]/;
                my $tok = substr($s, $tstart, $k - $tstart);

                if ($tok eq '--') {
                    # 以降はオプションとして解釈しない（位置引数の `-` 始まりを守る）。
                    $j = $k;
                    last OPTION_TOKEN;
                }

                my ($name) = $tok =~ /^([^=]+)=/;
                $name = $tok unless defined $name;

                if ($GIT_VALUE_OPTS{$name}) {
                    if ($tok =~ /=/) {
                        # 値が同一トークン内（= 形）。トークンごと落とす。
                        $j = $k;
                    } else {
                        # 値は次トークン（space 形）。両方落とす。
                        my $v = $k;
                        $v++ while $v < $n && substr($s, $v, 1) =~ /[ \t]/;
                        if ($v > $k) {
                            my $vend = $v;
                            $vend++ while $vend < $n && substr($s, $vend, 1) !~ /[ \t]/;
                            $j = $vend;
                        } else {
                            $j = $k;
                        }
                    }
                    next OPTION_TOKEN;
                }

                if ($tok =~ /^--[A-Za-z][A-Za-z0-9-]*$/ || $tok =~ /^-[A-Za-z0-9]+$/) {
                    # 値を取らないオプション（--no-pager, -P, --literal-pathspecs 等）。
                    $j = $k;
                    next OPTION_TOKEN;
                }

                last OPTION_TOKEN; # オプション語彙に一致しない = subcommand に到達
            }
            $i = $j;
            next;
        }
        $out .= substr($s, $i, 1);
        $i++;
    }
    return $out;
}

local $/;
my $s = <STDIN>;
$s = '' unless defined $s;

my ($line, $extra) = render_code($s, 0);
$s = join("\n", $line, @$extra);

# subshell / ブレースグループは「コマンド位置」でのみコマンドを開始する。
for (1 .. 4) {
    $s =~ s/(\A|[;&|\n]|&&|\|\|)([ \t]*)[({][ \t]*/$1$2; /g;
}
# 起点直後の env 代入と wrapper 語を落として、対象語を起点に隣接させる。
my $origin = qr/(\A|[;&|\n]|&&|\|\|)/;
for (1 .. 4) {
    $s =~ s/$origin([ \t]*)(?:[A-Za-z_][A-Za-z0-9_]*=\S*[ \t]+)+/$1$2/g;
    $s =~ s/$origin([ \t]*)(?:then|do|else|elif|!|command|exec|env|time|nohup|sudo)[ \t]+/$1$2/g;
}
$s = strip_git_global_options($s);
print $s;
PERL

normalize_command() {
  printf '%s' "$1" | perl -e "$_NORMALIZE_PERL"
}

# `printf '%s\n' "$text" | grep -qE "$ere"` と同じ判定を fork 無しで行う。
#   ere_matches <text> <ere>          （grep -qE 相当）
#   ere_matches_nocase <text> <ere>   （grep -qiE 相当）
#
# hook は 1 回の判定で 25 前後の grep パイプラインを起動し、それが hook 実行時間
# 150ms の半分を占めていた（Bash ツール呼び出しごとに毎回払う）。bash の =~ は
# grep と同じ POSIX ERE だが行の概念が無く、`^` が 2 行目以降に効かず
# `[^;&]*` が改行を跨ぐ。grep の「どの 1 行かが一致すれば真」に合わせるため
# 行に分割して各行を判定する。`\b` などの GNU 拡張は使えないので、rule の ERE は
# POSIX の範囲で書く（`([^A-Za-z0-9_]|$)` 等）。
ere_matches() {
  local _ere_text="$1" _ere="$2" _line
  while IFS= read -r _line || [ -n "$_line" ]; do
    [[ "$_line" =~ $_ere ]] && return 0
  done <<< "$_ere_text"
  return 1
}

ere_matches_nocase() {
  local _rc
  shopt -s nocasematch
  ere_matches "$1" "$2"
  _rc=$?
  shopt -u nocasematch
  return "$_rc"
}

# 標準形の中でコマンド起点（行頭 / ; / && / || / | / &）の直後に ERE が現れるか。
#   command_origin_matches <command> <ere>
# 戻り値: 0 = 一致、1 = 不一致、2 = 前処理失敗（呼び出し側が fail-closed に倒す）。
#
# 各 hook が `(^|&&|;|\|)` の境界を個別に書くと、改行・`&`・bare subshell `(`・
# `$( )` の扱いがばらつき、`echo x\ngit commit` のような複合コマンドが素通りした
# （2026-08-29 Codex 監査）。境界の定義は normalize_command の出力形（subshell と
# コマンド置換は行/`; ` に畳まれ、改行は起点として残る）に一本化する。
command_origin_matches() {
  local normalized
  if ! normalized=$(normalize_command "$1"); then
    return 2
  fi
  if [ -n "$1" ] && [ -z "$normalized" ]; then
    return 2
  fi
  ere_matches "$normalized" "(^|;|&&|\|\||\||&)[[:space:]]*($2)"
}

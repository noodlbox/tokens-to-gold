# noodlbox-app #3097 real-binary fixture (one line per hit)

Two DEV builds of `nbx` (2.8.0, debug assertions on), run by L8's #3097 scenario (`noodlbox/lane-evidence/awp-l8/3097/scenario/scenario4.sh`) on lease cbx_3069bfe03331, one isolated state root per arm, telemetry off, on abs-lang/abs @ cb1b3b671d0ee9fa9da9f7b02f86967953ffd10a (one checkout per arm under the same directory name, so every uid is equal across arms).

- **Head** (the one-line-per-hit block): noodlbox-app `design/3097-grep-group-by-file` at `61862c2615cb992fd961aeeed3512a70e006f494`, nbx sha256 `52635f7cc69c9361ce7797577a1e26e8fe34d46e0454544532ba9f1b3042010c`.
- **Base** (the headed block): noodlbox-app main `4b542d7173e04337bee3d0517af5585abb670861`, nbx sha256 `405dfb221fce6b4440dc3142145b41f2c7378ebfdc97382f4d89330b7a1b8bd5`.
- Raw outputs of that run: `scenario4-raw.tgz`, sha256 `b89bda7d8adbbcabeb5b7bd14c93fba9e13b4863f16d45d998823a1cba521d60`.

Query: the go34 abs-stepped-slices task text, `--intent implement`.

- `grep.head.stdout`: head, default grep, `--max-tokens 2000` (84 hits, 84 lines).
- `grep.base.stdout`: base, the same row (80 hits under 60 heading lines).
- `json.head.stdout`: head, `--format json --max-tokens 32000`, the D+id oracle for both (`budget.truncated == false`, 987 rows). The base binary's `.result` at this row is byte-identical.

sha256:
3e2ed60d2da13c1f7d14efe2a03a339feb340381ca0afcfbbbececed7f8efc8b  grep.base.stdout
e2ee0dfe37e1022256a93e54d79af526e039aaa9507e0566fbd3b7fea7d61eb5  grep.head.stdout
c7659c6a0fd8fd8b438f6034ecbcb56cc5244c0fd4ffb82ffca5edc2a4d5986a  json.head.stdout

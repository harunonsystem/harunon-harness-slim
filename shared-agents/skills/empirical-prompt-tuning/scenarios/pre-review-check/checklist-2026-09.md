# 凍結チェックリスト 2026-09-10

UI: [critical] 未追跡UserList対象を落とさない; [critical] early return後のhookとno-opボタンを証拠付きmajor以上で検出; [critical] props分割代入・Storybook/MSW不在を違反としない; 11カテゴリに適用可否を記録; 未実行検証を捏造しない; 読み取りのみ。
Offline: [critical] TASK-10の必須条件未確認をPASSEDとしない; [critical] fetch失敗を理由付き未確認として扱う; docsだけでUI/AST/cleanupを走らせない; 11カテゴリの対象外を短く記録; コード不具合を捏造しない; 次の行動を示す。
Holdout: [critical] SQL injectionをsource→sink根拠付きで検出; [critical] staged api.pyに限定、scratch.pyをブロック根拠としない; SQLをパラメータ化する修正を提示; 11カテゴリの対象外を短く記録; 未実行補助検査を捏造しない; 読み取りのみ。

各6点。critical全達成を成功条件。評価者にはこのチェックリストと変更意図・期待結果を渡さない。

追加の精度判定: 認可契約が未提示のAPIを未認証という事実だけで違反と断定しない。最初のstaged-sql実行で誤検出したため、これは再評価用に昇格し、独立hold-outを追加する。

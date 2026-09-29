# Two-browser test (about 5 minutes)

Checks that two people editing at once never overwrite each other. Use two browser
windows side by side (e.g. Chrome and a Chrome Incognito window, both logged in).
Put things back as they were at the end.

1. In **both** windows open **Shipments** (the tracker).
2. Pick one shipment and a free-text column, e.g. **Remarks**. Note its current value.
3. **Window A:** double-click that Remarks cell, type `A was here`, press Enter. It says "Saved Remarks".
4. **Window B** (don't refresh): double-click the **same** cell, type `B was here`, press Enter.
5. Window B shows **"Someone else changed this"** with A's value, who changed it and when. ✅
6. Click **Use theirs**. The cell shows `A was here`; nothing else changes.
7. Repeat steps 3-5 with new text, and this time click **Keep mine**. The cell keeps B's text,
   and after a refresh window A shows it too.
8. **Different fields don't clash:** in A edit **Remarks**, in B (no refresh) edit **POC** on
   the same shipment. Both save with no dialog; after a refresh both values are there. ✅
9. **Safe undo:** in A change a cell, then in B change the same cell. Back in A press
   Ctrl/⌘+Z (outside any text box). A says "…was changed by … since — not undone"
   and B's value stays. ✅
10. **Upload while editing:** in A upload a document on a shipment (Documents tab) while B
    edits a cell on the same shipment. Both changes are there after a refresh. ✅

Finally set the cells you touched back to their original values.

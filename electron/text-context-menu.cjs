function shouldShowTextEditingMenu(params = {}) {
  return Boolean(params.isEditable);
}

function createTextEditingMenuTemplate(params = {}) {
  const flags = params.editFlags || {};
  return [
    { label: "Undo", role: "undo", enabled: flags.canUndo !== false },
    { label: "Redo", role: "redo", enabled: flags.canRedo !== false },
    { type: "separator" },
    { label: "Cut", role: "cut", enabled: flags.canCut !== false },
    { label: "Copy", role: "copy", enabled: flags.canCopy !== false },
    { label: "Paste", role: "paste", enabled: flags.canPaste !== false },
    { type: "separator" },
    { label: "Select All", role: "selectAll", enabled: flags.canSelectAll !== false },
  ];
}

module.exports = {
  createTextEditingMenuTemplate,
  shouldShowTextEditingMenu,
};

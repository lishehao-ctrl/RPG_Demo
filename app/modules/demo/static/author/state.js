window.AuthorStudioV5State = {
  pages: ["compose", "shape", "build"],
  initialUiState(showDebug = false) {
    return {
      focus_mode: true,
      show_debug: Boolean(showDebug),
      active_tab: "author",
      active_page: "compose",
      panels: {
        structure_open: false,
        review_advanced_open: false,
      },
    };
  },
};

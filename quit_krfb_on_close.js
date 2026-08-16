function watchKrfbSetupWindow(window) {
  const resourceClass = window.resourceClass.toLowerCase();
  if (!window.normalWindow || (resourceClass !== "krfb" && resourceClass !== "org.kde.krfb")) {
    return;
  }

  window.closed.connect(() => {
    callDBus(
      "org.kde.krfb",
      "/MainApplication",
      "org.qtproject.Qt.QCoreApplication",
      "quit"
    );
  });
}

workspace.windowList().forEach(watchKrfbSetupWindow);
workspace.windowAdded.connect(watchKrfbSetupWindow);

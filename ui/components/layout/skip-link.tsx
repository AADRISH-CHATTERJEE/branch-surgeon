export function SkipLink() {
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[100] focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:shadow-md focus:ring-2 focus:ring-ring"
      onClick={(event) => {
        event.preventDefault();
        const main = document.getElementById("main-content");
        main?.focus({ preventScroll: true });
        window.scrollTo(0, 0);
      }}
    >
      Skip to content
    </a>
  );
}

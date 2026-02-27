(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.components = root.components || {};

  const { useRef, useEffect, useState } = React;

  /**
   * AnimatedContainer — replays a CSS animation each time `animationKey` changes.
   *
   * Props:
   *   animationKey  — any primitive; when it changes the animation class is re-applied
   *   className     — CSS class that holds the animation (e.g. "step-forward")
   *   tag           — wrapper element tag, default "div"
   *   children
   */
  function AnimatedContainer({ animationKey, className, tag = "div", children, ...rest }) {
    const ref = useRef(null);
    const prevKey = useRef(animationKey);
    const [animClass, setAnimClass] = useState(className || "");

    useEffect(() => {
      if (prevKey.current === animationKey) {
        return;
      }
      prevKey.current = animationKey;

      // Remove class to reset animation, then re-add on next frame
      setAnimClass("");
      const raf = requestAnimationFrame(() => {
        setAnimClass(className || "");
      });
      return () => cancelAnimationFrame(raf);
    }, [animationKey, className]);

    const Tag = tag;
    return (
      <Tag ref={ref} className={animClass} {...rest}>
        {children}
      </Tag>
    );
  }

  root.components.AnimatedContainer = AnimatedContainer;
})();

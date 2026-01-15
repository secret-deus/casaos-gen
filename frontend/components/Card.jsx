(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.components = root.components || {};

  const cx = root.utils?.cx || ((...parts) => parts.filter(Boolean).join(" "));

  function Card({ className, children, ...props }) {
    return (
      <section className={cx("card", className)} {...props}>
        {children}
      </section>
    );
  }

  function CardHeader({ className, title, subtitle, actions, children }) {
    return (
      <header className={cx("card__header", className)}>
        <div className="card__headerText">
          {title && <h3 className="card__title">{title}</h3>}
          {subtitle && <p className="card__subtitle">{subtitle}</p>}
          {children}
        </div>
        {actions && <div className="card__actions">{actions}</div>}
      </header>
    );
  }

  function CardBody({ className, children }) {
    return <div className={cx("card__body", className)}>{children}</div>;
  }

  root.components.Card = Card;
  root.components.CardHeader = CardHeader;
  root.components.CardBody = CardBody;
})();


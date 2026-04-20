import { useRef, useState } from "react";

interface LandingViewProps {
  loading: boolean;
  onImport: (payload: { text: string; name: string }) => Promise<void>;
}

export function LandingView({ loading, onImport }: LandingViewProps) {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("docker-compose.yml");
  const inputRef = useRef<HTMLInputElement | null>(null);

  return (
    <main className="landing">
      <div className="landing__hero">
        <span className="landing__eyebrow">CasaOS Compose Workspace</span>
        <h1>Compose in. CasaOS metadata out.</h1>
        <p>
          Import a compose file, refine app metadata, render multilingual output, and export the final CasaOS YAML
          from one workspace.
        </p>
      </div>

      <section className="landingCard">
        <div className="landingCard__actions">
          <button className="secondaryButton" type="button" onClick={() => inputRef.current?.click()}>
            Choose compose file
          </button>
          <input
            ref={inputRef}
            hidden
            type="file"
            accept=".yml,.yaml,text/yaml,text/plain"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) {
                return;
              }
              const fileText = await file.text();
              setText(fileText);
              setFileName(file.name);
            }}
          />
          <span className="landingCard__hint">Paste compose text below or load a file to start.</span>
        </div>

        <label className="field">
          <span>Compose file name</span>
          <input value={fileName} onChange={(event) => setFileName(event.target.value)} placeholder="docker-compose.yml" />
        </label>

        <label className="field field--grow">
          <span>Compose YAML</span>
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Paste docker-compose.yml here"
            rows={18}
            spellCheck={false}
          />
        </label>

        <div className="landingCard__footer">
          <button
            className="primaryButton"
            type="button"
            disabled={loading || !text.trim()}
            onClick={() => onImport({ text, name: fileName || "docker-compose.yml" })}
          >
            {loading ? "Importing..." : "Open workspace"}
          </button>
        </div>
      </section>
    </main>
  );
}

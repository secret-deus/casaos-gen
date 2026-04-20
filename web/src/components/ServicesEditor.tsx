import { useEffect, useMemo, useState } from "react";
import type { ServiceDescriptionChange, ServiceFieldType, ServiceMeta } from "../types";

type ServiceCollectionKey = keyof Pick<ServiceMeta, "envs" | "ports" | "volumes">;

interface ServicesEditorProps {
  services: Record<string, ServiceMeta>;
  saving: boolean;
  onSave: (changes: ServiceDescriptionChange[]) => Promise<void>;
}

type ServiceFilter = "all" | ServiceFieldType;

function cloneServices(services: Record<string, ServiceMeta>): Record<string, ServiceMeta> {
  return Object.fromEntries(
    Object.entries(services).map(([serviceName, service]) => [
      serviceName,
      {
        envs: service.envs.map((item) => ({ ...item })),
        ports: service.ports.map((item) => ({ ...item })),
        volumes: service.volumes.map((item) => ({ ...item })),
      },
    ]),
  );
}

function targetFor(serviceName: string, fieldType: ServiceFieldType, container: string): string {
  return `service:${serviceName}:${fieldType}:${container}`;
}

function diffServices(
  original: Record<string, ServiceMeta>,
  draft: Record<string, ServiceMeta>,
): ServiceDescriptionChange[] {
  const changes: ServiceDescriptionChange[] = [];
  const collections: Array<{ key: ServiceCollectionKey; fieldType: ServiceFieldType }> = [
    { key: "envs", fieldType: "env" },
    { key: "ports", fieldType: "port" },
    { key: "volumes", fieldType: "volume" },
  ];

  for (const [serviceName, service] of Object.entries(original)) {
    const draftService = draft[serviceName];
    if (!draftService) {
      continue;
    }
    for (const collection of collections) {
      const originalItems = service[collection.key];
      const draftItems = draftService[collection.key];
      for (let index = 0; index < originalItems.length; index += 1) {
        const originalItem = originalItems[index];
        const draftItem = draftItems[index];
        if (!draftItem) {
          continue;
        }
        if (draftItem.description !== originalItem.description) {
          changes.push({
            target: targetFor(serviceName, collection.fieldType, originalItem.container),
            value: draftItem.description,
          });
        }
      }
    }
  }

  return changes;
}

function ServiceCollectionSection({
  label,
  items,
  serviceName,
  collectionKey,
  fieldType,
  onChange,
}: {
  label: string;
  items: Array<{ item: ServiceMeta[ServiceCollectionKey][number]; index: number }>;
  serviceName: string;
  collectionKey: ServiceCollectionKey;
  fieldType: ServiceFieldType;
  onChange: (serviceName: string, collectionKey: ServiceCollectionKey, index: number, value: string) => void;
}) {
  if (!items.length) {
    return null;
  }

  return (
    <section className="serviceSection">
      <div className="serviceSection__title">{label}</div>
      <div className="serviceEntryList">
        {items.map(({ item, index }) => (
          <label key={`${collectionKey}-${item.container}`} className="serviceEntry">
            <div className="serviceEntry__header">
              <span className="serviceEntry__container">{item.container}</span>
              <span className="serviceEntry__flags">
                {item.multilang ? "multilang" : "single-language"}
                {item.user_input ? " user-input" : ""}
              </span>
            </div>
            <textarea
              data-focus-target={targetFor(serviceName, fieldType, item.container)}
              value={item.description}
              onChange={(event) => onChange(serviceName, collectionKey, index, event.target.value)}
              rows={3}
              spellCheck={false}
              placeholder={`Describe ${item.container}`}
            />
          </label>
        ))}
      </div>
    </section>
  );
}

export function ServicesEditor({ services, saving, onSave }: ServicesEditorProps) {
  const [draft, setDraft] = useState<Record<string, ServiceMeta>>(() => cloneServices(services));
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<ServiceFilter>("all");

  useEffect(() => {
    setDraft(cloneServices(services));
  }, [services]);

  const changes = useMemo(() => diffServices(services, draft), [draft, services]);
  const normalizedSearch = search.trim().toLowerCase();

  const filterMatches = (fieldType: ServiceFieldType) => filter === "all" || filter === fieldType;

  const filterItems = (items: ServiceMeta[ServiceCollectionKey], fieldType: ServiceFieldType) => {
    if (!filterMatches(fieldType)) {
      return [];
    }
    return items
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => {
        if (!normalizedSearch) {
          return true;
        }
        const haystack = `${item.container} ${item.description}`.toLowerCase();
        return haystack.includes(normalizedSearch);
      });
  };

  const visibleServices = useMemo(
    () =>
      Object.entries(draft)
        .map(([serviceName, service]) => {
          const nameMatches = normalizedSearch ? serviceName.toLowerCase().includes(normalizedSearch) : true;
          const visibleForType = (items: ServiceMeta[ServiceCollectionKey], fieldType: ServiceFieldType) => {
            if (!filterMatches(fieldType)) {
              return [];
            }
            if (nameMatches && normalizedSearch) {
              return items.map((item, index) => ({ item, index }));
            }
            return filterItems(items, fieldType);
          };
          const ports = visibleForType(service.ports, "port");
          const envs = visibleForType(service.envs, "env");
          const volumes = visibleForType(service.volumes, "volume");
          const hasMatches = ports.length || envs.length || volumes.length;
          if (!nameMatches && !hasMatches) {
            return null;
          }
          return {
            serviceName,
            service,
            ports,
            envs,
            volumes,
          };
        })
        .filter((entry): entry is NonNullable<typeof entry> => Boolean(entry)),
    [draft, filter, normalizedSearch],
  );

  const updateDraft = (serviceName: string, collectionKey: ServiceCollectionKey, index: number, value: string) => {
    setDraft((current) => {
      const service = current[serviceName];
      if (!service) {
        return current;
      }
      const collection = service[collectionKey];
      const item = collection[index];
      if (!item || item.description === value) {
        return current;
      }
      const nextCollection = collection.map((entry, entryIndex) =>
        entryIndex === index ? { ...entry, description: value } : entry,
      );
      return {
        ...current,
        [serviceName]: {
          ...service,
          [collectionKey]: nextCollection,
        },
      };
    });
  };

  return (
    <div className="servicesEditor">
      <div className="servicesEditor__toolbar">
        <span>{changes.length ? `${changes.length} unsaved service description(s)` : "Service descriptions are up to date"}</span>
        <div className="servicesEditor__actions">
          <button
            className="primaryButton"
            type="button"
            disabled={saving || changes.length === 0}
            onClick={() => void onSave(changes)}
          >
            {saving ? "Saving..." : "Save service descriptions"}
          </button>
        </div>
      </div>

      <div className="servicesEditor__filters">
        <input
          className="servicesEditor__search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Filter by service, container, or description"
        />
        <div className="servicesEditor__chips">
          {[
            { value: "all", label: "All" },
            { value: "port", label: "Ports" },
            { value: "env", label: "Envs" },
            { value: "volume", label: "Volumes" },
          ].map((option) => (
            <button
              key={option.value}
              className={`chipButton ${filter === option.value ? "chipButton--active" : ""}`}
              type="button"
              onClick={() => setFilter(option.value as ServiceFilter)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="serviceGroupList">
        {visibleServices.length ? (
          visibleServices.map(({ serviceName, service, ports, envs, volumes }) => (
            <article key={serviceName} className="serviceCard serviceCard--editable">
              <div className="serviceCard__title">{serviceName}</div>
              <div className="serviceCard__meta">
                <span>{service.envs.length} envs</span>
                <span>{service.ports.length} ports</span>
                <span>{service.volumes.length} volumes</span>
              </div>

              <ServiceCollectionSection
                label="Ports"
                items={ports}
                serviceName={serviceName}
                collectionKey="ports"
                fieldType="port"
                onChange={updateDraft}
              />
              <ServiceCollectionSection
                label="Environment"
                items={envs}
                serviceName={serviceName}
                collectionKey="envs"
                fieldType="env"
                onChange={updateDraft}
              />
              <ServiceCollectionSection
                label="Volumes"
                items={volumes}
                serviceName={serviceName}
                collectionKey="volumes"
                fieldType="volume"
                onChange={updateDraft}
              />
            </article>
          ))
        ) : (
          <div className="servicesEditor__empty">No service fields match the current filters.</div>
        )}
      </div>
    </div>
  );
}

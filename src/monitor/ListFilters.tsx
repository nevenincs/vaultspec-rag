import { Column, Grid, Search, Select, SelectItem } from "@carbon/react";

export type ListOptions = {
  page: number;
  pageSize: number;
  search: string;
  state: string;
  sort: string;
  order: string;
};
export const defaultListOptions: ListOptions = {
  page: 1,
  pageSize: 25,
  search: "",
  state: "",
  sort: "priority",
  order: "asc",
};

export function ListFilters({
  id,
  options,
  onChange,
  states,
  sorts,
  placeholder,
}: {
  id: string;
  options: ListOptions;
  onChange: (options: ListOptions) => void;
  states: [string, string][];
  sorts: [string, string][];
  placeholder: string;
}) {
  const change = (values: Partial<ListOptions>) =>
    onChange({ ...options, ...values, page: 1 });
  return (
    <Grid narrow className="monitor-grid monitor-list-filters">
      <Column sm={4} md={8} lg={7}>
        <Search
          id={`${id}-search`}
          labelText={placeholder}
          placeholder={placeholder}
          size="lg"
          value={options.search}
          onChange={(event) => change({ search: event.target.value })}
        />
      </Column>
      <Column sm={2} md={3} lg={3}>
        <Select
          id={`${id}-state`}
          labelText="Status"
          value={options.state}
          onChange={(event) => change({ state: event.target.value })}
        >
          <SelectItem value="" text="All statuses" />
          {states.map(([value, label]) => (
            <SelectItem key={value} value={value} text={label} />
          ))}
        </Select>
      </Column>
      <Column sm={2} md={3} lg={3}>
        <Select
          id={`${id}-sort`}
          labelText="Sort by"
          value={options.sort}
          onChange={(event) => change({ sort: event.target.value })}
        >
          {sorts.map(([value, label]) => (
            <SelectItem key={value} value={value} text={label} />
          ))}
        </Select>
      </Column>
      <Column sm={4} md={2} lg={3}>
        <Select
          id={`${id}-order`}
          labelText="Order"
          value={options.order}
          onChange={(event) => change({ order: event.target.value })}
        >
          <SelectItem value="desc" text="Descending" />
          <SelectItem value="asc" text="Ascending" />
        </Select>
      </Column>
    </Grid>
  );
}

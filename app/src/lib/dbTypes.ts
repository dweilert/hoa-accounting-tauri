export interface DbHandle {
  execute(
    sql: string,
    params?: unknown[]
  ): Promise<{ rowsAffected: number; lastInsertId?: number }>;
  select<T>(sql: string, params?: unknown[]): Promise<T>;
}

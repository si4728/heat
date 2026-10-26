-- IRIS database schema 3.7.0
-- Add a query-friendly exchanger-code copy to specification revisions.

ALTER TABLE heat_exchanger_spec_revision
ADD COLUMN exchanger_code VARCHAR(100);

UPDATE heat_exchanger_spec_revision
   SET exchanger_code = (
       SELECT e.equipment_code
         FROM heat_exchanger h
         JOIN equipment e ON e.equipment_id = h.equipment_id
        WHERE h.heat_exchanger_id = heat_exchanger_spec_revision.heat_exchanger_id
   );

-- The application migration also installs a trigger that inherits this stable
-- exchanger code when a new specification revision is created.

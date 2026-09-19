import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { reportSchema } from '../api';
import { safe } from '../test/fixtures';
import { ReportView } from './ReportView';

it('preserves coverage fields through API validation and exposes incomplete results', () => {
  const report = reportSchema.parse({
    ...safe, decision: 'REVIEW REQUIRED', analysis_complete: false,
    diagnostics: [{
      code: 'UNSUPPORTED_RESOURCE', severity: 'warning', message: 'Resource is outside modeled coverage.',
      phase: 'after', resource: 'aws_db_instance.database', attribute: 'publicly_accessible',
      source_file: 'main.tf', blocks_analysis: true,
    }],
  });
  render(<ReportView report={report} />);
  expect(screen.getByRole('alert')).toHaveTextContent('Analysis incomplete');
  expect(screen.getByText('aws_db_instance.database')).toBeVisible();
  expect(screen.getByText('UNSUPPORTED_RESOURCE')).toBeVisible();
  expect(screen.queryByText('SAFE TO MERGE')).not.toBeInTheDocument();
});

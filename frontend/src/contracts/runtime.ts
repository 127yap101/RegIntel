import Ajv2020 from 'ajv/dist/2020'
import type { ValidateFunction } from 'ajv'
import addFormats from 'ajv-formats'
import { CONTRACT_NAMES } from './generated'
import type { ContractName, ContractTypes } from './generated'
import schema from './schema.json'

function schemaPattern(pattern: string | undefined): RegExp {
  if (!pattern) throw new Error('Shared contract schema is incomplete.')
  return new RegExp(pattern, 'u')
}

const decimalPattern = schemaPattern(
  schema.$defs.QuantitativeValue.properties.normalized_value.anyOf.find(
    (entry) => 'pattern' in entry,
  )?.pattern,
)
const usernamePattern = schemaPattern(schema.$defs.UserIdentity.properties.username.pattern)
const errorCodePattern = schemaPattern(schema.$defs.ErrorDetail.properties.code.pattern)

const ajv = new Ajv2020({
  strict: true,
  strictNumbers: true,
  allErrors: false,
  coerceTypes: false,
  useDefaults: false,
  removeAdditional: false,
})
addFormats(ajv, { mode: 'full' })
ajv.addSchema(schema)

const validators = new Map<ContractName, ValidateFunction<unknown>>()
for (const name of CONTRACT_NAMES) {
  validators.set(name, ajv.compile<unknown>({ $ref: `${schema.$id}#/$defs/${name}` }))
}

/** Submitted values and validator internals never become error text. */
export class ContractValidationError extends Error {
  constructor() {
    super('Invalid shared contract.')
    this.name = 'ContractValidationError'
  }
}

function requireContract(condition: boolean): void {
  if (!condition) throw new ContractValidationError()
}

function requireUnique(values: readonly string[]): void {
  requireContract(new Set(values).size === values.length)
}

function requireWholePattern(pattern: RegExp, value: string): void {
  requireContract(pattern.exec(value)?.[0] === value)
}

function checkUnicode(value: string | null): void {
  if (value === null) return
  for (const character of value) {
    const first = character.charCodeAt(0)
    requireContract(character.length !== 1 || first < 0xd800 || first > 0xdfff)
  }
}

function checkPeriod(period: ContractTypes['FinancialPeriod']): void {
  checkUnicode(period.raw_label)
  switch (period.kind) {
    case 'INSTANT':
      requireContract(period.start_date === null && period.end_date === null)
      break
    case 'DURATION':
      requireContract(period.instant_date === null)
      if (period.start_date !== null && period.end_date !== null) {
        requireContract(period.end_date >= period.start_date)
      }
      break
    case 'UNKNOWN':
      requireContract(
        period.start_date === null && period.end_date === null && period.instant_date === null,
      )
      break
  }
}

function checkSpan(span: ContractTypes['TextSpan']): void {
  checkUnicode(span.quote)
  requireContract(span.end > span.start && span.end - span.start === Array.from(span.quote).length)
}

function checkRectangle(rectangle: ContractTypes['PdfRectangle']): void {
  requireContract(rectangle.x1 > rectangle.x0 && rectangle.y1 > rectangle.y0)
  requireContract(Number.isFinite(rectangle.x1 - rectangle.x0))
  requireContract(Number.isFinite(rectangle.y1 - rectangle.y0))
}

function dimensionsAgree(actual: number, declared: number): boolean {
  return Number.isFinite(actual) && Math.abs(actual - declared) <= Math.max(
    1e-12 * Math.max(Math.abs(actual), Math.abs(declared)),
    1e-9,
  )
}

function checkGeometry(geometry: ContractTypes['PageGeometry']): void {
  checkRectangle(geometry.media_box)
  checkRectangle(geometry.crop_box)
  requireContract(dimensionsAgree(geometry.media_box.x1 - geometry.media_box.x0, geometry.width))
  requireContract(dimensionsAgree(geometry.media_box.y1 - geometry.media_box.y0, geometry.height))
}

function checkCell(cell: ContractTypes['CellReference']): void {
  requireUnique(cell.row_label_cell_ids)
  requireUnique(cell.period_column_cell_ids)
  requireUnique(cell.unit_header_cell_ids)
  requireUnique(cell.basis_header_cell_ids)
  requireContract(Number.isSafeInteger(cell.row_index + cell.row_span))
  requireContract(Number.isSafeInteger(cell.column_index + cell.column_span))
}

function checkQuantity(quantity: ContractTypes['QuantitativeValue']): void {
  for (const label of [
    quantity.raw_value, quantity.raw_unit, quantity.normalized_unit,
    quantity.raw_currency, quantity.currency, quantity.raw_basis_label,
    quantity.denominator, quantity.stake_kind,
  ]) checkUnicode(label)
  if (quantity.normalized_value !== null) {
    requireWholePattern(decimalPattern, quantity.normalized_value)
  }
  checkPeriod(quantity.period)
  requireUnique(quantity.evidence_ids)
}

function checkTextEvidence(evidence: ContractTypes['TextEvidence']): void {
  checkGeometry(evidence.page_geometry)
  evidence.boxes.forEach(checkRectangle)
  checkSpan(evidence.span)
}

function checkCellEvidence(evidence: ContractTypes['CellEvidence']): void {
  checkGeometry(evidence.page_geometry)
  evidence.boxes.forEach(checkRectangle)
  checkCell(evidence.cell)
}

/** Mirror only model invariants; M1 still owns evidence/context acceptance. */
function checkSemantics(name: ContractName, value: unknown): void {
  switch (name) {
    case 'UserIdentity': {
      const user = value as ContractTypes['UserIdentity']
      requireWholePattern(usernamePattern, user.username)
      break
    }
    case 'UserEnvelope': {
      const envelope = value as ContractTypes['UserEnvelope']
      requireWholePattern(usernamePattern, envelope.data.username)
      break
    }
    case 'ErrorDetail': {
      const detail = value as ContractTypes['ErrorDetail']
      requireWholePattern(errorCodePattern, detail.code)
      break
    }
    case 'ApiError': {
      const error = value as ContractTypes['ApiError']
      requireWholePattern(errorCodePattern, error.code)
      checkUnicode(error.message)
      error.details.forEach((detail) => requireWholePattern(errorCodePattern, detail.code))
      break
    }
    case 'ErrorEnvelope': {
      const envelope = value as ContractTypes['ErrorEnvelope']
      requireWholePattern(errorCodePattern, envelope.error.code)
      checkUnicode(envelope.error.message)
      envelope.error.details.forEach((detail) => requireWholePattern(errorCodePattern, detail.code))
      break
    }
    case 'FinancialPeriod':
      checkPeriod(value as ContractTypes['FinancialPeriod'])
      break
    case 'QuantitativeValue':
      checkQuantity(value as ContractTypes['QuantitativeValue'])
      break
    case 'TextSpan':
      checkSpan(value as ContractTypes['TextSpan'])
      break
    case 'PdfRectangle':
      checkRectangle(value as ContractTypes['PdfRectangle'])
      break
    case 'PageGeometry':
      checkGeometry(value as ContractTypes['PageGeometry'])
      break
    case 'CellReference':
      checkCell(value as ContractTypes['CellReference'])
      break
    case 'TextEvidence':
      checkTextEvidence(value as ContractTypes['TextEvidence'])
      break
    case 'CellEvidence':
      checkCellEvidence(value as ContractTypes['CellEvidence'])
      break
    case 'EvidenceSupport': {
      const support = value as ContractTypes['EvidenceSupport']
      requireUnique(support.records.map((record) => record.id))
      for (const record of support.records) {
        if (record.kind === 'text') checkTextEvidence(record)
        else checkCellEvidence(record)
      }
      break
    }
    case 'RelationReference': {
      const relation = value as ContractTypes['RelationReference']
      requireUnique(relation.evidence_ids)
      if (relation.quantitative_context !== null) checkQuantity(relation.quantitative_context)
      break
    }
    case 'FilingLineage': {
      const lineage = value as ContractTypes['FilingLineage']
      checkUnicode(lineage.lineage_type)
      requireContract(lineage.parent_filing_id !== lineage.child_filing_id)
      break
    }
    case 'AmendmentEffect': {
      const effect = value as ContractTypes['AmendmentEffect']
      requireUnique(effect.affected_observation_ids)
      requireUnique(effect.new_observation_ids)
      requireUnique(effect.evidence_ids)
      break
    }
  }
}

/** Validate unknown wire data without coercing, stripping or defaulting it. */
export function parseContract<K extends ContractName>(name: K, value: unknown): ContractTypes[K] {
  const validate = validators.get(name)
  if (!validate || !validate(value)) throw new ContractValidationError()
  checkSemantics(name, value)
  return value as ContractTypes[K]
}

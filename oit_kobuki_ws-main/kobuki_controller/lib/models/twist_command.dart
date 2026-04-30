class TwistCommand {
  const TwistCommand({
    required this.linearX,
    required this.angularZ,
  });

  final double linearX;
  final double angularZ;

  static const zero = TwistCommand(linearX: 0, angularZ: 0);
}
